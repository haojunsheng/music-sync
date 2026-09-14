import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List
from music_sync.http import get_session
from music_sync.validator import check_blacklist, validate_candidate_match

# QQ 音乐专辑封面 CDN 模板（albummid 由搜索接口返回）
QQ_ALBUM_COVER_TMPL = "https://y.gtimg.cn/music/photo_new/T002R300x300M000{albummid}.jpg"


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
    """按优先级选取基准元数据：QQ 音乐 -> iTunes -> MusicBrainz -> 网易云 -> Fallback。"""
    # 1. QQ 音乐优先：中文曲库覆盖最全，发行信息最准
    meta = fetch_qq_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        if not meta.cover_url:
            itunes_meta = fetch_itunes_metadata(title, artist)
            if itunes_meta and itunes_meta.cover_url:
                meta.cover_url = itunes_meta.cover_url
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
