import os
import shutil
import subprocess
from typing import List
from rich.console import Console
from music_sync.config import load_config
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist

console = Console()

class YouTubeSource(BaseSource):
    @property
    def name(self) -> str:
        return "youtube"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        cfg = load_config()
        if not shutil.which("yt-dlp"):
            console.print("      [yellow]↳ YOUTUBE: 未找到 yt-dlp 可执行文件[/yellow]")
            return []

        query = f"{title} {artist}".strip()
        cmd = [
            "yt-dlp",
            f"ytsearch3:{query}",
            "--dump-json",
            "--no-playlist",
            "--quiet"
        ]
        if cfg.youtube_proxy:
            cmd.extend(["--proxy", cfg.youtube_proxy])
        if cfg.youtube_cookies_browser:
            cmd.extend(["--cookies-from-browser", cfg.youtube_cookies_browser])

        candidates = []
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            console.print("      [yellow]↳ YOUTUBE: yt-dlp 执行超时（国内直连需配置 youtube_proxy）[/yellow]")
            return candidates
        except FileNotFoundError:
            console.print("      [yellow]↳ YOUTUBE: 未找到 yt-dlp 可执行文件[/yellow]")
            return candidates
        except Exception as e:
            console.print(f"      [yellow]↳ YOUTUBE: yt-dlp 调用失败: {e}[/yellow]")
            return candidates

        if res.returncode != 0:
            tail = (res.stderr or "").strip().splitlines()
            console.print(f"      [yellow]↳ YOUTUBE: yt-dlp 返回码 {res.returncode}: {tail[-1] if tail else ''}[/yellow]")
            return candidates

        if not res.stdout:
            console.print("      [yellow]↳ YOUTUBE: yt-dlp 无输出结果[/yellow]")
            return candidates

        import json
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            raw_title = item.get("title", "")
            uploader = item.get("uploader", "")
            duration = int(item.get("duration", 0))

            is_bl, _ = check_blacklist(raw_title)
            if is_bl:
                continue

            webpage_url = item.get("webpage_url", "")
            if webpage_url:
                candidates.append(TrackCandidate(
                    source="youtube",
                    song_id=item.get("id", ""),
                    title=raw_title,
                    artist=uploader,
                    album="YouTube",
                    duration_seconds=duration,
                    quality="192k",
                    file_ext="m4a",
                    download_url=webpage_url
                ))
        return candidates
