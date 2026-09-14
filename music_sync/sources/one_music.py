from typing import List
from rich.console import Console
from music_sync.http import get_session
from music_sync.config import load_config
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist, validate_candidate_match

console = Console()

class OneMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "1music"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        cfg = load_config()
        token = cfg.token_1music
        if not token:
            console.print("      [yellow]↳ 1MUSIC: 未配置 token_1music，已跳过[/yellow]")
            return []

        session = get_session()
        query = f"{title} {artist}".strip()
        url = "https://api.1music.cc/search"
        params = {"q": query, "token": token}
        candidates = []
        try:
            resp = session.get(url, params=params, timeout=8)
        except Exception as e:
            console.print(f"      [yellow]↳ 1MUSIC 搜索请求失败: {e}[/yellow]")
            return candidates

        if resp.status_code != 200:
            console.print(f"      [yellow]↳ 1MUSIC 搜索返回 HTTP {resp.status_code}[/yellow]")
            return candidates

        try:
            items = resp.json().get("data", [])
        except ValueError:
            console.print("      [yellow]↳ 1MUSIC 搜索响应非 JSON（token 可能无效）[/yellow]")
            return candidates

        for item in items:
            song_name = item.get("title", "")
            singer = item.get("artist", "")
            album = item.get("album", "")
            dl_url = item.get("url", "")
            duration = item.get("duration", 0)

            if not validate_candidate_match(song_name, singer, title, artist):
                continue

            is_bl, _ = check_blacklist(f"{song_name} {album}")
            if is_bl:
                continue

            if dl_url:
                candidates.append(TrackCandidate(
                    source="1music",
                    song_id=item.get("id", ""),
                    title=song_name,
                    artist=singer,
                    album=album,
                    duration_seconds=duration,
                    quality="320k",
                    file_ext="mp3",
                    download_url=dl_url
                ))
        return candidates
