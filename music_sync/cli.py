import argparse
import sys
from rich.console import Console
from rich.table import Table

from music_sync.config import load_config, save_config, DEFAULT_CONFIG_FILE
from music_sync.netease import login_qr
from music_sync.pipeline import sync_single_track, sync_batch_csv

console = Console()

def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "y", "on")

def handle_login(args):
    console.print("[bold cyan]=== 网易云音乐二维码登录 ===[/bold cyan]")
    ok = login_qr()
    if ok:
        console.print("[bold green]登录成功！Cookie 已保存。[/bold green]")
    else:
        console.print("[bold red]登录未完成或失败。[/bold red]")
        sys.exit(1)

def handle_sync(args):
    sync_single_track(
        title=args.title,
        artist=args.artist,
        album=args.album or "",
        dry_run=args.dry_run,
        no_upload=args.no_upload,
        flac_only=getattr(args, "flac_only", False)
    )

def handle_batch(args):
    sync_batch_csv(
        csv_path=args.csv_file,
        dry_run=args.dry_run,
        no_upload=args.no_upload
    )

def handle_config(args):
    cfg = load_config()
    changed = False

    if args.qq_cookie is not None:
        cfg.qq_cookie = args.qq_cookie
        changed = True
    if args.netease_cookie is not None:
        cfg.netease_cookie = args.netease_cookie
        changed = True
    if args.tolerance_seconds is not None:
        cfg.tolerance_seconds = args.tolerance_seconds
        changed = True
    if args.use_system_proxy is not None:
        cfg.use_system_proxy = _as_bool(args.use_system_proxy)
        changed = True
    if args.bilibili_cookie is not None:
        cfg.bilibili_cookie = args.bilibili_cookie
        changed = True
    if args.token_1music is not None:
        cfg.token_1music = args.token_1music
        changed = True
    if args.quality_priority is not None:
        # 形如 "flac,ape,320k"，按优先级从高到低；未列入的档位一律拒绝
        cfg.quality_priority = [
            q.strip().lower() for q in args.quality_priority.split(",") if q.strip()
        ]
        changed = True
    if args.allow_lossy is not None:
        cfg.allow_lossy_fallback = _as_bool(args.allow_lossy)
        changed = True

    if changed:
        save_config(cfg)
        console.print("[green]配置已更新！[/green]")

    table = Table(title=f"当前配置 ({DEFAULT_CONFIG_FILE})")
    table.add_column("配置项", style="cyan")
    table.add_column("值", style="magenta")

    table.add_row("tolerance_seconds", str(cfg.tolerance_seconds))
    table.add_row("quality_priority", str(cfg.quality_priority))
    table.add_row("allow_lossy_fallback", str(cfg.allow_lossy_fallback))
    table.add_row("sources", str(cfg.sources))
    table.add_row("qq_cookie", f"{cfg.qq_cookie[:30]}..." if len(cfg.qq_cookie) > 30 else (cfg.qq_cookie or "(未配置)"))
    table.add_row("netease_cookie", f"{cfg.netease_cookie[:30]}..." if len(cfg.netease_cookie) > 30 else (cfg.netease_cookie or "(未配置)"))
    table.add_row("use_system_proxy", str(cfg.use_system_proxy))
    table.add_row("1music_token", f"{cfg.token_1music[:15]}..." if len(cfg.token_1music) > 15 else (cfg.token_1music or "(未配置)"))
    table.add_row("download_dir", cfg.download_dir)
    table.add_row("bilibili_cookie", f"{cfg.bilibili_cookie[:20]}..." if len(cfg.bilibili_cookie) > 20 else (cfg.bilibili_cookie or "(未配置)"))

    console.print(table)

def main():
    parser = argparse.ArgumentParser(
        prog="music-sync",
        description="music-sync 个人音乐跨平台同步与网易云云盘直传工具"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # login
    subparsers.add_parser("login", help="扫码登录网易云音乐并保存 Cookie")

    # sync
    sync_parser = subparsers.add_parser("sync", help="同步单首歌曲")
    sync_parser.add_argument("title", help="歌曲名称，例如：晴天")
    sync_parser.add_argument("--artist", "-a", default="", help="歌手名称，例如：周杰伦")
    sync_parser.add_argument("--album", default="", help="专辑名称（可选）")
    sync_parser.add_argument("--dry-run", action="store_true", help="只预览匹配结果，不下载与上传")
    sync_parser.add_argument("--no-upload", action="store_true", help="仅下载打标，不上传网易云云盘")
    sync_parser.add_argument("--flac-only", action="store_true", help="强制只接受无损音源")

    # batch
    batch_parser = subparsers.add_parser("batch", help="批量同步 CSV 文件中的歌曲")
    batch_parser.add_argument("csv_file", help="CSV 文件路径 (格式: title,artist[,album])")
    batch_parser.add_argument("--dry-run", action="store_true", help="只预览，不下载与上传")
    batch_parser.add_argument("--no-upload", action="store_true", help="仅下载打标，不上传")

    # config
    config_parser = subparsers.add_parser("config", help="查看或修改配置")
    config_parser.add_argument("--qq-cookie", help="设置 QQ 音乐会员 Cookie")
    config_parser.add_argument("--netease-cookie", help="设置网易云登录 Cookie")
    config_parser.add_argument("--tolerance-seconds", type=int, help="设置时长容差（秒）")
    config_parser.add_argument("--use-system-proxy", help="是否走系统代理 (true/false)")
    config_parser.add_argument("--bilibili-cookie", help="设置 B站 Cookie")
    config_parser.add_argument("--1music-token", dest="token_1music", help="设置 1music.cc 令牌")
    config_parser.add_argument(
        "--quality-priority",
        help="可接受音质档位，按优先级从高到低用逗号分隔，例如 flac,ape,320k"
    )
    config_parser.add_argument("--allow-lossy", help="是否允许 320k 等有损兜底 (true/false)")

    args = parser.parse_args()

    if args.command == "login":
        handle_login(args)
    elif args.command == "sync":
        handle_sync(args)
    elif args.command == "batch":
        handle_batch(args)
    elif args.command == "config":
        handle_config(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
