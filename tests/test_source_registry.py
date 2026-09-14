"""音源注册表测试。

注册表是流水线遍历音源的唯一入口：键名、实例化、未知源处理都必须稳定，
否则 pipeline 的 cfg.sources 配置会静默失配。
"""
import pytest

from music_sync.sources import SOURCE_REGISTRY, get_source
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.sources.bilibili import BilibiliAudioSource
from music_sync.sources.kugou import KugouMusicSource
from music_sync.sources.kuwo import KuwoMusicSource
from music_sync.sources.migu import MiguMusicSource
from music_sync.sources.netease import NetEaseMusicSource
from music_sync.sources.one_music import OneMusicSource
from music_sync.sources.qq import QQMusicSource
from music_sync.sources.youtube import YouTubeSource

EXPECTED = {
    "qq": QQMusicSource,
    "migu": MiguMusicSource,
    "kuwo": KuwoMusicSource,
    "netease": NetEaseMusicSource,
    "kugou": KugouMusicSource,
    "bilibili": BilibiliAudioSource,
    "1music": OneMusicSource,
    "youtube": YouTubeSource,
}


class TestSourceRegistry:
    def test_registry_contains_all_expected_sources(self):
        assert set(SOURCE_REGISTRY) == set(EXPECTED)

    def test_registry_maps_to_expected_classes(self):
        for key, cls in EXPECTED.items():
            assert SOURCE_REGISTRY[key] is cls

    def test_get_source_returns_instance_of_expected_class(self):
        for key, cls in EXPECTED.items():
            assert isinstance(get_source(key), cls)

    def test_unknown_source_raises_value_error(self):
        with pytest.raises(ValueError):
            get_source("spotify")

    def test_every_source_reports_matching_name(self):
        # name 属性必须与注册键一致，否则日志与配置会错位
        for key, cls in EXPECTED.items():
            assert cls().name == key

    def test_every_source_subclasses_base_and_implements_search(self):
        for cls in EXPECTED.values():
            inst = cls()
            assert isinstance(inst, BaseSource)
            assert callable(inst.search_and_resolve)


class TestTrackCandidate:
    def test_defaults(self):
        cand = TrackCandidate(
            source="qq",
            song_id="MID",
            title="断桥残雪",
            artist="许嵩",
            album="",
            duration_seconds=227,
            quality="flac",
            file_ext="flac",
        )
        assert cand.download_url is None
        assert cand.extra_data is None

    def test_fields_are_set(self):
        cand = TrackCandidate(
            source="kuwo",
            song_id="1",
            title="t",
            artist="a",
            album="al",
            duration_seconds=227,
            quality="320k",
            file_ext="mp3",
            download_url="http://x/a.mp3",
        )
        assert cand.download_url == "http://x/a.mp3"
        assert cand.duration_seconds == 227
