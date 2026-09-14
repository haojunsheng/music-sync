import hashlib
from typing import List
from rich.console import Console
from music_sync.http import get_session
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist, validate_duration, validate_candidate_match

console = Console()

class KugouMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "kugou"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        session = get_session()
        query = f"{title} {artist}".strip()
        search_url = "http://mobilecdn.kugou.com/api/v3/search/song"
        params = {
            "format": "json",
            "keyword": query,
            "page": 1,
            "pagesize": 10,
            "showtype": 1
        }
        candidates = []
        matched = 0
        try:
            resp = session.get(search_url, params=params, timeout=8)
        except Exception as e:
            console.print(f"      [yellow]↳ KUGOU 搜索请求失败: {e}[/yellow]")
            return candidates

        if resp.status_code != 200:
            console.print(f"      [yellow]↳ KUGOU 搜索返回 HTTP {resp.status_code}[/yellow]")
            return candidates

        try:
            info = resp.json().get("data", {}).get("info", [])
        except ValueError:
            console.print("      [yellow]↳ KUGOU 搜索响应非 JSON[/yellow]")
            return candidates

        for item in info:
            song_name = item.get("songname", "")
            singer = item.get("singername", "")
            album = item.get("album_name", "")
            duration = item.get("duration", 0)
            file_hash = item.get("sqhash") or item.get("320hash") or item.get("hash")

            # 1. 严格校验歌名和歌手匹配
            if not validate_candidate_match(song_name, singer, title, artist):
                continue

            # 2. 校验黑名单
            is_bl, _ = check_blacklist(f"{song_name} {album}")
            if is_bl:
                continue

            # 3. 校验时长
            if not validate_duration(duration, target_duration):
                continue

            matched += 1

            if file_hash:
                play_url_api = f"https://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={file_hash}"
                try:
                    p_resp = session.get(play_url_api, timeout=5)
                except Exception as e:
                    console.print(f"      [yellow]↳ KUGOU playInfo 请求失败: {e}[/yellow]")
                    continue
                if p_resp.status_code == 200:
                    try:
                        p_data = p_resp.json()
                    except ValueError:
                        console.print("      [yellow]↳ KUGOU playInfo 响应非 JSON[/yellow]")
                        continue
                    dl_url = p_data.get("url")
                    ext = p_data.get("extName", "mp3").lower()
                    if dl_url:
                        candidates.append(TrackCandidate(
                            source="kugou",
                            song_id=file_hash,
                            title=song_name,
                            artist=singer,
                            album=album,
                            duration_seconds=duration,
                            quality="flac" if ext == "flac" else "320k",
                            file_ext=ext,
                            download_url=dl_url
                        ))
        if not candidates and matched:
            console.print(
                f"      [yellow]↳ KUGOU: {matched} 首匹配曲目未返回直链"
                f"（付费/VIP 或 playInfo 老接口已失效）[/yellow]"
            )
        return candidates
