from typing import List
from rich.console import Console
from music_sync.http import get_session
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist, validate_candidate_match
from music_sync.netease_crypto import weapi_encrypt

console = Console()

class NetEaseMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "netease"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
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

        diag_done = False
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

            # Player URL（weapi 接口，需有效登录态 Cookie 才返回直链）
            url_api = "https://music.163.com/weapi/song/enhance/player/url/v1"
            data = {"ids": f"[{song_id}]", "level": "lossless", "encodeType": "flac"}
            enc = weapi_encrypt(data)
            try:
                u_resp = session.post(url_api, data=enc, headers={"Referer": "https://music.163.com"}, timeout=8)
            except Exception as e:
                console.print(f"      [yellow]↳ NETEASE 直链接口请求失败: {e}[/yellow]")
                break

            if u_resp.status_code != 200:
                console.print(f"      [yellow]↳ NETEASE 直链接口返回 HTTP {u_resp.status_code}[/yellow]")
                break

            try:
                payload = u_resp.json()
            except ValueError:
                console.print("      [yellow]↳ NETEASE 直链接口返回空响应（weapi 已废弃，需有效登录 Cookie）[/yellow]")
                diag_done = True
                break

            url_data = (payload.get("data") or [{}])[0]
            song_url = url_data.get("url")
            level = url_data.get("level", "standard")
            ext = url_data.get("type", "mp3").lower()
            if song_url:
                candidates.append(TrackCandidate(
                    source="netease",
                    song_id=song_id,
                    title=song_name,
                    artist=artist_name,
                    album=album,
                    duration_seconds=duration_sec,
                    quality="flac" if level in ("lossless", "hires") else "320k",
                    file_ext=ext if ext in ("flac", "mp3") else "mp3",
                    download_url=song_url
                ))
        if not candidates and songs and not diag_done:
            console.print("      [yellow]↳ NETEASE: 未取到直链（需登录/会员 Cookie）[/yellow]")
        return candidates
