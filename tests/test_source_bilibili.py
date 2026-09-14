"""B 站音源测试。

回归点：搜索接口对未登录请求返回 412 风控，应返回空而不是抛错。
"""
import pytest

from music_sync.sources.bilibili import BilibiliAudioSource

SEARCH_URL_KEY = "api.bilibili.com/x/web-interface/search/type"
PLAYURL_URL_KEY = "api.bilibili.com/x/player/playurl"


def _search_payload(videos):
    return {
        "data": {
            "result": [
                {
                    "bvid": v["bvid"],
                    "title": v["title"],
                    "author": v.get("author", "UP"),
                    "duration": v.get("duration", "3:47"),
                    "id": v.get("cid", 111),
                }
                for v in videos
            ]
        }
    }


def _playurl_payload(base_url="http://bi/audio.m4a"):
    return {"data": {"dash": {"audio": [{"baseUrl": base_url}]}}}


class TestBilibiliParsing:
    def test_hits_and_returns_m4a(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"bvid": "BV1xx", "title": "许嵩 断桥残雪", "author": "某UP", "duration": "3:47"}]
                )),
                PLAYURL_URL_KEY: fake_response(200, _playurl_payload()),
            }
        )
        patch_session("music_sync.sources.bilibili.get_session", stub)

        out = BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "bilibili"
        assert cand.song_id == "BV1xx"
        assert cand.file_ext == "m4a"
        assert cand.download_url == "http://bi/audio.m4a"

    def test_duration_string_is_parsed(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"bvid": "BV1", "title": "断桥残雪", "duration": "4:03"}]
                )),
                PLAYURL_URL_KEY: fake_response(200, _playurl_payload()),
            }
        )
        patch_session("music_sync.sources.bilibili.get_session", stub)
        out = BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert out[0].duration_seconds == 243

    def test_regression_412_returns_empty(self, stub_session, patch_session, fake_response):
        """回归：触发风控（HTTP 412）时返回空且不崩溃。"""
        stub = stub_session({SEARCH_URL_KEY: fake_response(412, text="<html>出错啦</html>")})
        patch_session("music_sync.sources.bilibili.get_session", stub)
        assert BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_regression_html_body_returns_empty(self, stub_session, patch_session, fake_response):
        """回归：200 但返回 HTML（非 JSON）时优雅降级。"""
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, text="<!DOCTYPE html><html>")})
        patch_session("music_sync.sources.bilibili.get_session", stub)
        assert BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_keyword_highlight_tags_are_stripped(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"bvid": "BV1", "title": '<em class="keyword">断桥残雪</em> 许嵩'}]
                )),
                PLAYURL_URL_KEY: fake_response(200, _playurl_payload()),
            }
        )
        patch_session("music_sync.sources.bilibili.get_session", stub)
        out = BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert out[0].title == "断桥残雪 许嵩"
        assert "<em" not in out[0].title

    def test_blacklisted_title_filtered(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"bvid": "BV1", "title": "断桥残雪 (Live版)"}]
                )),
                PLAYURL_URL_KEY: fake_response(200, _playurl_payload()),
            }
        )
        patch_session("music_sync.sources.bilibili.get_session", stub)
        assert BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_empty_dash_audio_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload([{"bvid": "BV1", "title": "断桥残雪"}])),
                PLAYURL_URL_KEY: fake_response(200, json_data={"data": {"dash": {"audio": []}}}),
            }
        )
        patch_session("music_sync.sources.bilibili.get_session", stub)
        assert BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_playurl_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload([{"bvid": "BV1", "title": "断桥残雪"}])),
                PLAYURL_URL_KEY: fake_response(403, text="forbidden"),
            }
        )
        patch_session("music_sync.sources.bilibili.get_session", stub)
        assert BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_empty_result_list_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data={"data": {"result": []}})})
        patch_session("music_sync.sources.bilibili.get_session", stub)
        assert BilibiliAudioSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
