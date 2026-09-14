"""网易云音源测试。

回归点：weapi/player/url 接口在未登录/cookie 失效时会返回 200 + **空 body**，
旧实现直接 resp.json() 会抛异常并被静默吞掉。这里要求优雅降级。
"""
import pytest

from music_sync.sources.netease import NetEaseMusicSource

SEARCH_URL_KEY = "music.163.com/api/search/get/web"
PLAYER_URL_KEY = "weapi/song/enhance/player/url/v1"


def _search_payload(songs):
    return {
        "result": {
            "songs": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "artists": [{"name": n} for n in s["artists"]],
                    "album": {"name": s.get("album", "")},
                    "duration": s.get("duration", 227000),
                }
                for s in songs
            ]
        }
    }


def _player_payload(url, level="lossless", ext="flac"):
    return {"data": [{"url": url, "level": level, "type": ext}]}


class TestNeteaseParsing:
    def test_hits_lossless_and_reports_flac(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 27646693, "name": "断桥残雪", "artists": ["许嵩"], "album": "许嵩早期单曲集"}]
                )),
                PLAYER_URL_KEY: fake_response(200, _player_payload("http://ne/song.flac")),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)

        out = NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "netease"
        assert cand.song_id == "27646693"
        assert cand.title == "断桥残雪"
        assert cand.artist == "许嵩"
        assert cand.quality == "flac"
        assert cand.file_ext == "flac"
        assert cand.download_url == "http://ne/song.flac"

    def test_standard_level_reports_320k(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                PLAYER_URL_KEY: fake_response(200, _player_payload("http://ne/s.mp3", level="standard", ext="mp3")),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        out = NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert out[0].quality == "320k"

    def test_empty_url_returns_empty(self, stub_session, patch_session, fake_response):
        """VIP 曲目未登录时 url 为 null。"""
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                PLAYER_URL_KEY: fake_response(200, _player_payload(None)),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_regression_empty_body_does_not_crash(self, stub_session, patch_session, fake_response):
        """回归：直链接口返回 200 + 空 body 时必须优雅降级。"""
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                PLAYER_URL_KEY: fake_response(200, text=""),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_player_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                PLAYER_URL_KEY: fake_response(403, text="forbidden"),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_artist_mismatch_filtered(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["沐萧"]}]
                )),
                PLAYER_URL_KEY: fake_response(200, _player_payload("http://ne/s.flac")),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_blacklisted_title_filtered(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪 (Live)", "artists": ["许嵩"]}]
                )),
                PLAYER_URL_KEY: fake_response(200, _player_payload("http://ne/s.flac")),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_search_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(500, text="err")})
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
