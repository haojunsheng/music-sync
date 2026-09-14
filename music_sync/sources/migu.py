import json
from typing import List
from rich.console import Console
from music_sync.http import get_session
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist, validate_candidate_match

console = Console()

class MiguMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "migu"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        session = get_session()
        query = f"{title} {artist}".strip()
        url = "https://m.music.migu.cn/migu/remoting/scr_search_tag"
        params = {
            "rows": 10,
            "type": 2,
            "keyword": query,
            "pgc": 1
        }
        headers = {
            "Referer": "https://m.music.migu.cn/",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
        }
        candidates = []
        try:
            resp = session.get(url, params=params, headers=headers, timeout=8)
        except Exception as e:
            console.print(f"      [yellow]↳ MIGU 搜索请求失败: {e}[/yellow]")
            return candidates

        if resp.status_code != 200:
            console.print(f"      [yellow]↳ MIGU 搜索返回 HTTP {resp.status_code}[/yellow]")
            return candidates

        try:
            data = resp.json()
        except ValueError:
            console.print("      [yellow]↳ MIGU 接口已失效（返回非 JSON 页面），需更换新接口[/yellow]")
            return candidates

        musics = data.get("musics", []) if isinstance(data, dict) else []
        for item in musics:
            song_name = item.get("songName", "")
            singer = item.get("singerName", "")
            album = item.get("albumName", "")
            mp3_url = item.get("mp3", "")
            sq_url = item.get("flac", "") or item.get("sq", "")

            if not validate_candidate_match(song_name, singer, title, artist):
                continue

            is_bl, _ = check_blacklist(f"{song_name} {album}")
            if is_bl:
                continue

            dl_url = sq_url or mp3_url
            quality = "flac" if sq_url else "320k"
            ext = "flac" if sq_url else "mp3"

            if dl_url:
                candidates.append(TrackCandidate(
                    source="migu",
                    song_id=item.get("id", ""),
                    title=song_name,
                    artist=singer,
                    album=album,
                    duration_seconds=target_duration,
                    quality=quality,
                    file_ext=ext,
                    download_url=dl_url
                ))
        if not candidates and musics:
            console.print("      [yellow]↳ MIGU: 有搜索结果但无可用直链（mp3/flac 字段为空）[/yellow]")
        return candidates
