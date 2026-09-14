"""1music 音源测试。

该源依赖 token，未配置时应直接返回空（不发请求）。
"""
import pytest

from music_sync import config as config_mod
from music_sync.sources.one_music import OneMusicSource

SEARCH_URL_KEY = "api.1music.cc/search"


@pytest.fixture
def with_token():
    cfg = config_mod.load_config()
    cfg.token_1music = "TK-TEST"
    config_mod.save_config(cfg)
    return cfg


def _payload(items):
    return {"data": items}


class TestOneMusicSource:
    def test_missing_token_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, _payload([]))})
        patch_session("music_sync.sources.one_music.get_session", stub)
        assert OneMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
        # 未配置 token 时不应发起任何请求
        assert stub.calls == []

    def test_hits_and_returns_mp3(self, with_token, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _payload(
                    [
                        {
                            "id": "S1",
                            "title": "断桥残雪",
                            "artist": "许嵩",
                            "album": "许嵩早期单曲集",
                            "url": "http://1music/a.mp3",
                            "duration": 227,
                        }
                    ]
                ))
            }
        )
        patch_session("music_sync.sources.one_music.get_session", stub)

        out = OneMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "1music"
        assert cand.song_id == "S1"
        assert cand.quality == "320k"
        assert cand.file_ext == "mp3"
        assert cand.download_url == "http://1music/a.mp3"

    def test_artist_mismatch_filtered(self, with_token, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _payload(
                    [{"title": "断桥残雪", "artist": "沐萧", "url": "http://1music/a.mp3"}]
                ))
            }
        )
        patch_session("music_sync.sources.one_music.get_session", stub)
        assert OneMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_missing_url_yields_no_candidate(self, with_token, stub_session, patch_session, fake_response):
        stub = stub_session(
            {SEARCH_URL_KEY: fake_response(200, _payload([{"title": "断桥残雪", "artist": "许嵩"}]))}
        )
        patch_session("music_sync.sources.one_music.get_session", stub)
        assert OneMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_non_json_response_returns_empty(self, with_token, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, text="<html>bad token</html>")})
        patch_session("music_sync.sources.one_music.get_session", stub)
        assert OneMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_http_error_returns_empty(self, with_token, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(401, text="unauthorized")})
        patch_session("music_sync.sources.one_music.get_session", stub)
        assert OneMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
