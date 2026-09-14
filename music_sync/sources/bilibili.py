from typing import List
from rich.console import Console
from music_sync.http import get_session
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.config import load_config
from music_sync.validator import check_blacklist

console = Console()

class BilibiliAudioSource(BaseSource):
    @property
    def name(self) -> str:
        return "bilibili"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        cfg = load_config()
        session = get_session()
        query = f"{title} {artist}".strip()
        search_url = "https://api.bilibili.com/x/web-interface/search/type"
        params = {"search_type": "video", "keyword": query}
        headers = {"Referer": "https://www.bilibili.com"}
        if cfg.bilibili_cookie:
            headers["Cookie"] = cfg.bilibili_cookie

        candidates = []
        try:
            resp = session.get(search_url, params=params, headers=headers, timeout=8)
        except Exception as e:
            console.print(f"      [yellow]↳ BILIBILI 搜索请求失败: {e}[/yellow]")
            return candidates

        if resp.status_code == 412:
            console.print("      [yellow]↳ BILIBILI 触发风控 HTTP 412，需配置 bilibili_cookie[/yellow]")
            return candidates
        if resp.status_code != 200:
            console.print(f"      [yellow]↳ BILIBILI 搜索返回 HTTP {resp.status_code}[/yellow]")
            return candidates

        try:
            results = resp.json().get("data", {}).get("result", []) or []
        except ValueError:
            console.print("      [yellow]↳ BILIBILI 搜索响应非 JSON（可能被风控拦截）[/yellow]")
            return candidates

        for item in results:
            bvid = item.get("bvid", "")
            raw_title = item.get("title", "").replace('<em class="keyword">', '').replace('</em>', '')
            author = item.get("author", "")
            duration_str = item.get("duration", "0:0")
            parts = duration_str.split(":")
            duration_sec = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0

            is_bl, _ = check_blacklist(raw_title)
            if is_bl:
                continue

            if bvid:
                # Extract audio playurl via bilibili player api
                play_api = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={item.get('id', '')}&fnval=16"
                p_resp = session.get(play_api, headers=headers, timeout=8)
                if p_resp.status_code == 200:
                    dash = p_resp.json().get("data", {}).get("dash", {})
                    audio_list = dash.get("audio", [])
                    if audio_list:
                        audio_url = audio_list[0].get("baseUrl")
                        candidates.append(TrackCandidate(
                            source="bilibili",
                            song_id=bvid,
                            title=raw_title,
                            artist=author,
                            album="Bilibili",
                            duration_seconds=duration_sec,
                            quality="192k",
                            file_ext="m4a",
                            download_url=audio_url
                        ))
                else:
                    console.print(
                        f"      [yellow]↳ BILIBILI playurl 返回 HTTP {p_resp.status_code}"
                        f"（未登录时 dash 常为空）[/yellow]"
                    )
        if not candidates and results:
            console.print("      [yellow]↳ BILIBILI: 有搜索结果但未取到音频流[/yellow]")
        return candidates
