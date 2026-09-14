import csv
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
from rich.console import Console
from rich.table import Table

from music_sync.config import load_config
from music_sync.http import get_session
from music_sync.metadata import get_official_metadata
from music_sync.validator import validate_audio_file
from music_sync.lyrics import get_lyrics
from music_sync.tagger import apply_tags_and_verify
from music_sync.netease import NetEaseClient
from music_sync.sources import get_source, SOURCE_REGISTRY
from music_sync.sources.base import TrackCandidate

console = Console()

def download_file(url: str, output_path: str, extra_headers: dict = None) -> bool:
    session = get_session()
    try:
        resp = session.get(url, headers=extra_headers or {}, stream=True, timeout=30)
        if resp.status_code == 200:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            return True
    except Exception as e:
        console.print(f"[red]下载失败: {e}[/red]")
    return False

def sync_single_track(title: str, artist: str = "", album: str = "", dry_run: bool = False, no_upload: bool = False, flac_only: bool = False) -> bool:
    cfg = load_config()
    console.print(f"\n[bold cyan]>>> 开始处理: {title} - {artist}[/bold cyan]")

    # M1: 官方元数据锚点
    console.print("[dim]M1: 获取官方基准元数据...[/dim]")
    meta = get_official_metadata(title, artist)
    target_title = meta.title or title
    target_artist = meta.artist or artist
    target_album = album or meta.album
    target_duration = meta.duration_seconds
    console.print(f"  [green]✓[/green] 基准元数据: [bold]{target_title}[/bold] - [bold]{target_artist}[/bold] (时长: {target_duration}s, 来源: {meta.source})")

    # M2: 遍历音源搜索
    console.print("[dim]M2: 遍历音源抓取...[/dim]")
    selected_candidate: Optional[TrackCandidate] = None

    # 仅当显式指定 flac_only、或用户未开启有损回退时，才强制只接受 FLAC。
    # 旧实现里的 `or cfg.quality_priority == ["flac"]` 会让 allow_lossy_fallback 永远失效
    # （默认 quality_priority 恒为 ["flac"]，导致该条件恒真）。
    only_flac = flac_only or not cfg.allow_lossy_fallback

    for source_name in cfg.sources:
        if source_name not in SOURCE_REGISTRY:
            continue
        console.print(f"  [dim]↳ 正在检索音源 [{source_name.upper()}]...[/dim]")
        try:
            source = get_source(source_name)
            candidates = source.search_and_resolve(target_title, target_artist, target_duration)
            if candidates:
                console.print(f"    [cyan][+] {source_name.upper()}: 找到 {len(candidates)} 个候选曲目:[/cyan]")
                for c in candidates:
                    console.print(f"      • {c.title} - {c.artist} | 格式: {c.file_ext} | 音质: {c.quality} | 时长: {c.duration_seconds}s")

                valid_candidates = candidates
                if only_flac:
                    valid_candidates = [c for c in candidates if c.quality == "flac" or c.file_ext == "flac"]
                    if not valid_candidates:
                        console.print(f"      [yellow]↳ (该源未提供 FLAC 无损格式，已跳过)[/yellow]")
                        continue

                # 排序质量
                quality_order = {q: i for i, q in enumerate(cfg.quality_priority)}
                valid_candidates.sort(key=lambda c: quality_order.get(c.quality, 99))
                selected_candidate = valid_candidates[0]
                console.print(f"    [bold green]✓ 成功命中音源 [{selected_candidate.source.upper()}] 音质: {selected_candidate.quality.upper()}[/bold green]")
                break
            else:
                console.print(f"    [dim]  [-] {source_name.upper()}: 未获得可用候选[/dim]")
        except Exception as e:
            console.print(f"    [dim]  [-] {source_name.upper()}: 请求异常 ({e})[/dim]")
            continue

    if not selected_candidate:
        if only_flac:
            console.print(f"[bold red]❌ 未找到匹配的 FLAC 无损音源（已开启仅限 FLAC 无损模式）: {title} - {artist}[/bold red]")
        else:
            console.print(f"[bold red]❌ 未找到匹配的可用音源: {title} - {artist}[/bold red]")
        return False

    if dry_run:
        console.print(f"[yellow]⚡ [Dry-Run 模式] 命中候选: {selected_candidate.title} | 音源: {selected_candidate.source} | 格式: {selected_candidate.file_ext} | 下载地址: {selected_candidate.download_url}[/yellow]")
        return True

    # M4: 下载音频
    dl_dir = Path(os.path.expanduser(cfg.download_dir))
    dl_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = f"{target_artist} - {target_title}".replace("/", "_").replace("\\", "_")
    output_path = str(dl_dir / f"{safe_filename}.{selected_candidate.file_ext}")

    console.print(f"[dim]M4: 开始下载音频到: {output_path}[/dim]")
    if selected_candidate.source == "youtube":
        # YouTube 特殊处理 (yt-dlp)
        cmd = ["yt-dlp", "-x", "--audio-format", "m4a", "-o", output_path, selected_candidate.download_url]
        subprocess.run(cmd, capture_output=True)
        ok = os.path.exists(output_path)
    else:
        headers = {}
        if selected_candidate.source == "bilibili":
            headers = {"Referer": "https://www.bilibili.com"}
        ok = download_file(selected_candidate.download_url, output_path, headers)

    if not ok or not os.path.exists(output_path):
        console.print("[red]❌ 音频文件下载失败[/red]")
        return False

    # 实测时长二次校验
    valid, actual_len, msg = validate_audio_file(output_path, target_duration, cfg.tolerance_seconds)
    if not valid:
        console.print(f"[red]❌ 文件时长校验失败: {msg}，丢弃文件[/red]")
        try:
            os.remove(output_path)
        except Exception:
            pass
        return False
    console.print(f"  [green]✓[/green] 音频实测时长校验通过 ({actual_len:.1f}s)")

    # M5: 获取歌词与写入标签
    console.print("[dim]M5: 获取歌词与写入元数据标签...[/dim]")
    qq_mid = selected_candidate.song_id if selected_candidate.source == "qq" else ""
    lyrics, lrc_ok = get_lyrics(target_title, target_artist, qq_mid, target_duration)

    tag_ok, tag_msg = apply_tags_and_verify(
        output_path,
        title=target_title,
        artist=target_artist,
        album=target_album,
        lyrics=lyrics,
        cover_url=meta.cover_url
    )
    console.print(f"  [green]✓[/green] {tag_msg} (歌词: {'获取成功' if lyrics else '无'})")

    if no_upload:
        console.print(f"[bold green]✨ 完成（已跳过上传）: 本地路径 {output_path}[/bold green]")
        return True

    # M6: 网易云云盘查重与上传
    console.print("[dim]M6: 网易云云盘同步...[/dim]")
    ne_client = NetEaseClient()
    if ne_client.check_cloud_song_exists(target_title, target_artist):
        console.print(f"[yellow]⚠️ 网易云云盘中已存在歌曲: {target_title} - {target_artist}，跳过上传[/yellow]")
        return True

    upload_ok = ne_client.upload_to_cloud(output_path, target_title, target_artist, target_album)
    return upload_ok

def sync_batch_csv(csv_path: str, dry_run: bool = False, no_upload: bool = False):
    if not os.path.exists(csv_path):
        console.print(f"[red]CSV 文件不存在: {csv_path}[/red]")
        return

    songs = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("title", "").strip()
            artist = row.get("artist", "").strip()
            album = row.get("album", "").strip()
            if title:
                songs.append({"title": title, "artist": artist, "album": album})

    console.print(f"[bold cyan]开始批量同步，共 {len(songs)} 首歌曲...[/bold cyan]")
    success_count = 0
    fail_count = 0

    results = []
    for s in songs:
        try:
            ok = sync_single_track(s["title"], s["artist"], s["album"], dry_run, no_upload)
            if ok:
                success_count += 1
                results.append((s["title"], s["artist"], "成功", "green"))
            else:
                fail_count += 1
                results.append((s["title"], s["artist"], "失败", "red"))
        except Exception as e:
            fail_count += 1
            results.append((s["title"], s["artist"], f"异常: {e}", "red"))

    table = Table(title="批量同步结果汇总")
    table.add_column("歌名", style="cyan")
    table.add_column("歌手", style="magenta")
    table.add_column("状态")

    for t, a, status, color in results:
        table.add_row(t, a, f"[{color}]{status}[/{color}]")

    console.print(table)
    console.print(f"\n[bold]总计: {len(songs)} 首 | 成功: [green]{success_count}[/green] | 失败: [red]{fail_count}[/red][/bold]")
