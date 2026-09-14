from typing import List
from rich.console import Console
from music_sync.config import load_config
from music_sync.http import get_session
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist, validate_candidate_match
from music_sync.netease_crypto import eapi_encrypt

console = Console()

EAPI_HOST = "https://interface.music.163.com/eapi"
PLAYER_URL_PATH = "/api/song/enhance/player/url/v1"

# 直链音质档位，从高到低尝试；实际得到的音质以响应里的 level 为准
QUALITY_ATTEMPTS = [("lossless", "flac"), ("exhigh", "mp3")]


class NetEaseMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "netease"

    def _fetch_player_url(self, session, cookie: str, song_id: str, level: str, encode_type: str):
        """经 eapi 请求播放直链，返回响应中的 data[0]；失败返回 None。

        eapi 是现行接口，需要带上登录态 Cookie；已废弃的 weapi 会返回 200 + 空 body。
        """
        payload = {"ids": f"[{song_id}]", "level": level, "encodeType": encode_type}
        try:
            params = eapi_encrypt(PLAYER_URL_PATH, payload)
            resp = session.post(
                EAPI_HOST + PLAYER_URL_PATH,
                data={"params": params},
                headers={"Referer": "https://music.163.com", "Cookie": cookie},
                timeout=8,
            )
            if resp.status_code != 200:
                return None
            data = resp.json().get("data") or [{}]
            return data[0] or {}
        except Exception:
            return None

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        cfg = load_config()
        cookie = cfg.netease_cookie or ""
        session = get_session()
        query = f"{title} {artist}".strip()
        search_url = "https://music.163.com/api/search/get/web"
        params = {"s": query, "type": 1, "limit": 10}
        candidates = []
        try:
            resp = session.get(search_url, params=params, timeout=8)
        except Exception as e:
            console.print(f"      [yellow]↳ NETEASE 搜索请求失败: {e}[/yellow]")
            return candidates

        if resp.status_code != 200:
            console.print(f"      [yellow]↳ NETEASE 搜索返回 HTTP {resp.status_code}[/yellow]")
            return candidates

        try:
            songs = resp.json().get("result", {}).get("songs", [])
        except ValueError:
            console.print("      [yellow]↳ NETEASE 搜索响应非 JSON[/yellow]")
            return candidates

        if not cookie:
            console.print("      [yellow]↳ NETEASE: 未配置 netease_cookie，eapi 直链接口需要登录态[/yellow]")

        eapi_failed = False
        for song in songs:
            song_id = str(song.get("id"))
            song_name = song.get("name", "")
            artists = song.get("artists", [])
            artist_name = "/".join(a.get("name", "") for a in artists)
            album = song.get("album", {}).get("name", "")
            duration_ms = song.get("duration", 0)
            duration_sec = int(duration_ms / 1000)

            if not validate_candidate_match(song_name, artist_name, title, artist):
                continue

            is_bl, _ = check_blacklist(f"{song_name} {album}")
            if is_bl:
                continue

            # 按音质档位从高到低请求，拿到直链即止
            url_data = None
            for level, encode_type in QUALITY_ATTEMPTS:
                data = self._fetch_player_url(session, cookie, song_id, level, encode_type)
                if data is None:
                    eapi_failed = True
                    break
                if data.get("url"):
                    url_data = data
                    break

            if not url_data:
                continue

            actual_level = str(url_data.get("level") or "standard").lower()
            if actual_level in ("lossless", "hires"):
                quality, ext = "flac", "flac"
            elif actual_level in ("exhigh", "higher"):
                quality, ext = "320k", "mp3"
            else:
                # standard(128k) 等低音质仍如实上报，由上层策略决定是否采用
                quality, ext = "128k", "mp3"

            candidates.append(TrackCandidate(
                source="netease",
                song_id=song_id,
                title=song_name,
                artist=artist_name,
                album=album,
                duration_seconds=duration_sec,
                quality=quality,
                file_ext=ext,
                download_url=url_data.get("url")
            ))

        if not candidates and songs:
            if eapi_failed:
                console.print("      [yellow]↳ NETEASE: eapi 直链接口调用失败（网络或响应异常）[/yellow]")
            elif not cookie:
                console.print("      [yellow]↳ NETEASE: 未取到直链，请先执行 music-sync login 登录[/yellow]")
            else:
                console.print("      [yellow]↳ NETEASE: 未取到直链（该曲目可能为 VIP 专享，或 Cookie 已失效）[/yellow]")
        return candidates
