import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List
from rich.console import Console

from music_sync.config import load_config
from music_sync.http import get_session
from music_sync.validator import check_blacklist, is_artist_match, validate_candidate_match

console = Console()

# QQ 音乐专辑封面 CDN 模板（albummid 由搜索接口返回）
QQ_ALBUM_COVER_TMPL = "https://y.gtimg.cn/music/photo_new/T002R300x300M000{albummid}.jpg"

# Apple Music 走 Web Play 通道：网页播放器那种 token（iss=AMPWebPlay）在
# api.music.apple.com 上会被直接拒成 401，必须用 amp-api 域名并带 Origin 头。
APPLE_MUSIC_API_BASE = "https://amp-api.music.apple.com"
# 封面模板里 {w}x{h} 的替换尺寸；Apple 原图最长边可达 3000px 以上
APPLE_ARTWORK_SIZE = 1000

# Apple 曲名尾部的版本/出处括注，例如 "后会无期 (《诡案》网络剧插曲)"、"断桥残雪 (Live)"
_EDITION_SUFFIX_RE = re.compile(r"\s*[（(\[【][^）)\]】]*[）)\]】]\s*")


def _strip_edition_suffix(name: str) -> str:
    """去掉曲名尾部的括注，得到「干净歌名」。"""
    return _EDITION_SUFFIX_RE.sub(" ", name or "").strip()


def _reorder_artists(artist_name: str, preferred: str) -> str:
    """把用户查询的歌手提到合作歌手列表首位，保持本地归档目录稳定。

    归档目录取的是首位歌手，而 Apple 的排列常与 QQ 相反（"后会无期" Apple 给
    "汪苏泷 & 徐良"、QQ 给 "徐良/汪苏泷"）。用户拿"徐良"去查却被归进 汪苏泷/，
    同一首歌在曲库里就分成了两份。这里只在查询歌手确实出现在列表里、且不在首位时
    重排一次，不增不减任何歌手。
    """
    preferred = (preferred or "").strip()
    if not preferred:
        return artist_name
    parts = [p.strip() for p in re.split(r"[、&/,]", artist_name or "") if p.strip()]
    if len(parts) < 2:
        return artist_name
    hits = [i for i, part in enumerate(parts) if is_artist_match(part, preferred)]
    if not hits or hits[0] == 0:
        return artist_name
    idx = hits[0]
    return "/".join([parts[idx]] + parts[:idx] + parts[idx + 1:])


@dataclass
class OfficialMetadata:
    title: str
    artist: str
    album: str
    duration_seconds: int
    cover_url: str = ""
    release_year: str = ""
    source: str = ""


def _norm_text(value: str) -> str:
    """归一化文本用于精确比对：忽略大小写与空格。"""
    return (value or "").lower().replace(" ", "")


def fetch_qq_metadata(title: str, artist: str) -> Optional[OfficialMetadata]:
    """从 QQ 音乐搜索接口取基准元数据（首选基准源）。

    选它作为首选的依据：中文曲库覆盖最全，songname/singer/albumname/interval
    直接对应官方发行信息，且能拿到 albummid 与 pubtime 用于封面和发行年份。

    注意必须做匹配校验：这是模糊搜索，结果里会混入 Live/翻唱/伴奏等版本。
    """
    session = get_session()
    query = f"{title} {artist}".strip()
    url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
    params = {"p": 1, "n": 10, "w": query, "format": "json", "t": 0, "cr": 1}
    headers = {"Referer": "https://y.qq.com/"}

    try:
        resp = session.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        songs = resp.json().get("data", {}).get("song", {}).get("list", [])
    except Exception:
        return None

    fallback: Optional[OfficialMetadata] = None
    for song in songs:
        song_name = song.get("songname", "")
        singers = song.get("singer", [])
        singer_name = "/".join(s.get("name", "") for s in singers)
        interval = song.get("interval", 0)

        if not song_name or not interval or interval <= 0:
            continue
        # 歌名/歌手必须匹配，否则模糊搜索的首条可能是无关曲目
        if not validate_candidate_match(song_name, singer_name, title, artist):
            continue
        # 排除 Live / DJ / 伴奏 / 翻唱等版本，避免用非原版时长锚定整条流水线
        is_blacklisted, _ = check_blacklist(f"{song_name} {song.get('albumname', '')}")
        if is_blacklisted:
            continue

        album_mid = song.get("albummid", "")
        pubtime = song.get("pubtime", 0)
        meta = OfficialMetadata(
            title=song_name,
            artist=singer_name or artist,
            album=song.get("albumname", ""),
            duration_seconds=int(interval),
            cover_url=QQ_ALBUM_COVER_TMPL.format(albummid=album_mid) if album_mid else "",
            release_year=str(datetime.fromtimestamp(pubtime, tz=timezone.utc).year) if pubtime else "",
            source="QQMusic",
        )

        # 歌名完全一致者优先，避免 "断桥残雪 (Live)" / "断桥残雪 (柔情版)" 抢先命中
        if _norm_text(song_name) == _norm_text(title):
            return meta
        if fallback is None:
            fallback = meta

    return fallback


def fetch_itunes_metadata(title: str, artist: str, regions: List[str] = None) -> Optional[OfficialMetadata]:
    if regions is None:
        regions = ["CN", "TW", "HK", "US"]
    session = get_session()
    query = f"{title} {artist}".strip()

    for country in regions:
        try:
            url = "https://itunes.apple.com/search"
            params = {
                "term": query,
                "entity": "song",
                "country": country,
                "limit": 10
            }
            resp = session.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for item in results:
                    track_name = item.get("trackName", "")
                    artist_name = item.get("artistName", "")
                    # 严格校验歌名和歌手匹配
                    title_match = title.lower() in track_name.lower() or track_name.lower() in title.lower()
                    artist_match = not artist or (artist.lower() in artist_name.lower() or artist_name.lower() in artist.lower())

                    if title_match and artist_match:
                        duration_ms = item.get("trackTimeMillis", 0)
                        duration_sec = int(duration_ms / 1000) if duration_ms else 0
                        artwork = item.get("artworkUrl100", "")
                        if artwork:
                            artwork = artwork.replace("100x100bb.jpg", "600x600bb.jpg").replace("100x100bb.png", "600x600bb.png")

                        release_date = item.get("releaseDate", "")
                        release_year = release_date[:4] if release_date else ""

                        return OfficialMetadata(
                            title=track_name,
                            artist=artist_name,
                            album=item.get("collectionName", ""),
                            duration_seconds=duration_sec,
                            cover_url=artwork,
                            release_year=release_year,
                            source=f"iTunes ({country})"
                        )
        except Exception:
            continue
    return None

def _apple_artwork_url(artwork: dict) -> str:
    """把 Apple 的 `{w}x{h}bb.jpg` 模板换成高分辨率封面地址。"""
    template = (artwork or {}).get("url") or ""
    if not template:
        return ""
    return template.replace("{w}", str(APPLE_ARTWORK_SIZE)).replace("{h}", str(APPLE_ARTWORK_SIZE))


def fetch_apple_music_metadata(title: str, artist: str, cfg=None) -> Optional[OfficialMetadata]:
    """从 Apple Music 取基准元数据（需先在配置里提供 apple_music_token）。

    这是唯一能拿到「发行级」信息的源：毫秒级时长、ISRC、精确发行日期，
    以及最长边 3000px 以上的封面（QQ/iTunes 只给 300~600px）。

    **只做元数据与封面锚点。** Apple Music 的完整音轨受 FairPlay DRM 保护，
    开发者 token 换不到可解密的音频流（previews 只有 30 秒），本项目也不做
    DRM 绕过。要下载音频走 sources/ 下的普通音源。

    cfg 可外部传入，避免每首歌都重新读一次配置文件。
    """
    cfg = cfg if cfg is not None else load_config()
    token = (cfg.apple_music_token or "").strip()
    if not token:
        return None
    storefront = (cfg.apple_music_storefront or "cn").strip().lower() or "cn"

    session = get_session()
    url = f"{APPLE_MUSIC_API_BASE}/v1/catalog/{storefront}/search"
    params = {
        "term": f"{title} {artist}".strip(),
        "types": "songs",
        "limit": 10,
        "extend": "audioTraits",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "https://music.apple.com",
        "Referer": "https://music.apple.com/",
    }

    try:
        resp = session.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code == 401:
            console.print(
                "[yellow]↳ Apple Music token 已失效或被拒绝，重新获取后执行: "
                'music-sync config --apple-music-token "<token>"[/yellow]'
            )
            return None
        if resp.status_code != 200:
            return None
        songs = ((resp.json().get("results") or {}).get("songs") or {}).get("data") or []
    except Exception:
        return None

    # 三档命中优先级：曲名逐字一致 > 去掉括注后一致 > 第一个通过校验的
    stripped_hit: Optional[OfficialMetadata] = None
    fallback: Optional[OfficialMetadata] = None
    for item in songs:
        attrs = item.get("attributes") or {}
        song_name = attrs.get("name", "")
        artist_name = attrs.get("artistName", "")
        duration_ms = attrs.get("durationInMillis", 0)

        if not song_name or not duration_ms or duration_ms <= 0:
            continue
        # 模糊搜索结果里会混入 Live/翻唱/他人专辑的曲目，必须校验
        if not validate_candidate_match(song_name, artist_name, title, artist):
            continue
        is_blacklisted, _ = check_blacklist(f"{song_name} {attrs.get('albumName', '')}")
        if is_blacklisted:
            continue

        # Apple 的中文曲库爱把网剧/影视出处写进曲名（"后会无期 (《诡案》网络剧插曲)"）。
        # 直接拿来当 target_title，会让文件名和 ID3 标题都比别的源多一截，同一首歌在
        # 两轮同步里变成两个文件，M4 的「本地已有就复用」也就失效了。
        # 只在去掉括注后与用户查询完全一致时才换回用户那份干净写法。
        stripped_name = _strip_edition_suffix(song_name)
        use_clean_title = (
            bool(stripped_name)
            and bool((title or "").strip())
            and _norm_text(stripped_name) == _norm_text(title)
        )
        meta = OfficialMetadata(
            title=title.strip() if use_clean_title else song_name,
            artist=_reorder_artists(artist_name, artist) or artist,
            album=attrs.get("albumName", ""),
            duration_seconds=int(round(duration_ms / 1000)),
            cover_url=_apple_artwork_url(attrs.get("artwork")),
            release_year=(attrs.get("releaseDate") or "")[:4],
            source="AppleMusic",
        )
        # 逐字同名者直接采用，避免 "断桥残雪 (Live)" 抢先命中
        if _norm_text(song_name) == _norm_text(title):
            return meta
        if use_clean_title:
            if stripped_hit is None:
                stripped_hit = meta
            continue
        if fallback is None:
            fallback = meta

    return stripped_hit or fallback


def fetch_musicbrainz_metadata(title: str, artist: str) -> Optional[OfficialMetadata]:
    session = get_session()
    headers = {"User-Agent": "music-sync/1.0 ( contact@example.com )"}
    query = f'recording:"{title}" AND artist:"{artist}"'
    try:
        url = "https://musicbrainz.org/ws/2/recording/"
        params = {"query": query, "fmt": "json", "limit": 5}
        resp = session.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            recordings = data.get("recordings", [])
            for rec in recordings:
                length_ms = rec.get("length", 0)
                duration_sec = int(length_ms / 1000) if length_ms else 0
                releases = rec.get("releases", [])
                album = releases[0].get("title", "") if releases else ""
                release_date = releases[0].get("date", "") if releases else ""
                release_year = release_date[:4] if release_date else ""

                artist_credit = rec.get("artist-credit", [])
                artist_name = artist_credit[0].get("name", artist) if artist_credit else artist

                if duration_sec > 0:
                    return OfficialMetadata(
                        title=rec.get("title", title),
                        artist=artist_name,
                        album=album,
                        duration_seconds=duration_sec,
                        release_year=release_year,
                        source="MusicBrainz"
                    )
    except Exception:
        pass
    return None

def fetch_netease_metadata(title: str, artist: str) -> Optional[OfficialMetadata]:
    session = get_session()
    query = f"{title} {artist}".strip()
    try:
        url = "https://music.163.com/api/search/get/web"
        params = {"s": query, "type": 1, "limit": 5, "offset": 0}
        resp = session.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            songs = data.get("result", {}).get("songs", [])
            for song in songs:
                song_name = song.get("name", "")
                artists = song.get("artists", song.get("ar", []))
                artist_name = "/".join(a.get("name", "") for a in artists) if artists else ""
                # 校验歌名/歌手，避免模糊搜索第一条命中无关歌曲而污染基准元数据
                if not validate_candidate_match(song_name, artist_name, title, artist):
                    continue

                duration_ms = song.get("dt", song.get("duration", 0))
                duration_sec = int(duration_ms / 1000) if duration_ms else 0
                album_info = song.get("album", song.get("al", {}))
                album = album_info.get("name", "")
                cover = album_info.get("picUrl", "")

                return OfficialMetadata(
                    title=song_name,
                    artist=artist_name or artist,
                    album=album,
                    duration_seconds=duration_sec,
                    cover_url=cover,
                    source="NetEase"
                )
    except Exception:
        pass
    return None

def get_official_metadata(title: str, artist: str) -> OfficialMetadata:
    """按优先级选取基准元数据。

    配了 apple_music_token 且 apple_music_priority=True（默认）时 Apple Music 排第一：
    发行元数据最权威（毫秒级时长 / ISRC / 精确发行日期），封面最长边可到 3000px。
    把 priority 关掉后 Apple Music 退到 QQ 音乐之后、iTunes 之前——中文曲目优先用
    QQ 的发行信息，非中文曲目仍由 Apple 兜住。

    无论 Apple 排第几，未命中都会继续走
    QQ 音乐 -> iTunes -> MusicBrainz -> 网易云 -> Fallback。
    """
    cfg = load_config()
    apple_available = bool((cfg.apple_music_token or "").strip())
    apple_first = apple_available and cfg.apple_music_priority

    # 0. Apple Music 置顶（仅「配了 token 且 priority 打开」时参与）
    if apple_first:
        meta = fetch_apple_music_metadata(title, artist, cfg=cfg)
        if meta and meta.duration_seconds > 0:
            return meta

    # 1. QQ 音乐优先：中文曲库覆盖最全，发行信息最准
    meta = fetch_qq_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        if not meta.cover_url:
            itunes_meta = fetch_itunes_metadata(title, artist)
            if itunes_meta and itunes_meta.cover_url:
                meta.cover_url = itunes_meta.cover_url
        return meta

    # 1.5 Apple Music 降级位（配了 token 但 priority 关掉时）
    if apple_available:
        meta = fetch_apple_music_metadata(title, artist, cfg=cfg)
        if meta and meta.duration_seconds > 0:
            return meta

    # 2. iTunes
    meta = fetch_itunes_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        return meta

    # 3. MusicBrainz（缺封面时用网易云补齐）
    meta = fetch_musicbrainz_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        if not meta.cover_url:
            ne_meta = fetch_netease_metadata(title, artist)
            if ne_meta and ne_meta.cover_url:
                meta.cover_url = ne_meta.cover_url
        return meta

    # 4. 网易云
    meta = fetch_netease_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        return meta

    return OfficialMetadata(
        title=title,
        artist=artist,
        album="",
        duration_seconds=0,
        source="Fallback"
    )
