import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "music-sync"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_COOKIE_FILE = DEFAULT_CONFIG_DIR / "netease_cookie.json"

DEFAULT_BLACKLIST_KEYWORDS = [
    "dj", "慢摇", "remix", "翻唱", "live", "伴奏", "串烧", "铃声", "纯音乐",
    "减速", "加速", "变调", "伴奏版", "伴奏带", "卡拉ok", "翻唱版", "现场版",
    "夜店", "电音", "抖音版", "手机铃声", "动态歌词", "cover", "inst",
    "instrumental", "acoustic", "piano", "karaoke", "mix", "edit",
    "speed up", "slowed", "reverb", "tribute", "ringtone", "sped up",
    "nightcore", "8d audio", "bass boosted", "snippet", "teaser"
]

@dataclass
class Config:
    tolerance_seconds: int = 10
    # 可接受音质档位，按优先级从高到低排列；未列入的档位一律拒绝。
    # 默认策略：优先无损（flac/ape），没有无损时接受 320k，低于 320k 的一概不接受。
    quality_priority: List[str] = field(default_factory=lambda: ["flac", "ape", "320k"])
    allow_lossy_fallback: bool = True
    sources: List[str] = field(default_factory=lambda: ["qq", "migu", "kuwo", "netease", "kugou", "bilibili", "youtube", "1music"])
    qq_cookie: str = ""
    netease_cookie: str = ""
    use_system_proxy: bool = False
    token_1music: str = ""
    blacklist_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_BLACKLIST_KEYWORDS))
    download_dir: str = str(Path.home() / "Music" / "music-sync")
    upload_extra_headers: Dict[str, str] = field(default_factory=dict)
    bilibili_cookie: str = ""
    youtube_proxy: str = ""
    youtube_cookies_browser: str = ""

def load_config() -> Config:
    if not DEFAULT_CONFIG_FILE.exists():
        cfg = Config()
        save_config(cfg)
        return cfg
    try:
        with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "1music_token" in data and "token_1music" not in data:
            data["token_1music"] = data.pop("1music_token")
        return Config(**{k: v for k, v in data.items() if k in Config.__annotations__})
    except Exception:
        return Config()

def save_config(cfg: Config) -> None:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    if "token_1music" in data:
        data["1music_token"] = data.pop("token_1music")
    with open(DEFAULT_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
