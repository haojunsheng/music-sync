from typing import Dict, Type
from music_sync.sources.base import BaseSource
from music_sync.sources.qq import QQMusicSource
from music_sync.sources.migu import MiguMusicSource
from music_sync.sources.kuwo import KuwoMusicSource
from music_sync.sources.netease import NetEaseMusicSource
from music_sync.sources.kugou import KugouMusicSource
from music_sync.sources.bilibili import BilibiliAudioSource
from music_sync.sources.one_music import OneMusicSource
from music_sync.sources.youtube import YouTubeSource

SOURCE_REGISTRY: Dict[str, Type[BaseSource]] = {
    "qq": QQMusicSource,
    "migu": MiguMusicSource,
    "kuwo": KuwoMusicSource,
    "netease": NetEaseMusicSource,
    "kugou": KugouMusicSource,
    "bilibili": BilibiliAudioSource,
    "1music": OneMusicSource,
    "youtube": YouTubeSource,
}

def get_source(name: str) -> BaseSource:
    cls = SOURCE_REGISTRY.get(name)
    if not cls:
        raise ValueError(f"Unknown source: {name}")
    return cls()
