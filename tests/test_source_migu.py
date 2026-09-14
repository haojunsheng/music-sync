"""咪咕音源测试。

回归点：scr_search_tag 老接口现已返回 HTML 页面（非 JSON），
必须优雅降级为"空结果"而不是抛异常。
"""
import pytest

from music_sync.sources.migu import MiguMusicSource

SEARCH_URL_KEY = "m.music.migu.cn"


def _payload(musics):
    return {"musics": musics}


class TestMiguParsing:
    def test_regression_html_response_returns_empty(self, stub_session, patch_session, fake_response):
        """回归：接口返回 HTML 而非 JSON 时不得崩溃。"""
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, text="<!doctype html><html>...")})
        patch_session("music_sync.sources.migu.get_session", stub)
        assert MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_prefers_flac_when_available(self, stub_session, patch_session, fake_response):
        payload = _payload(
            [
                {
                    "songName": "断桥残雪",
                    "singerName": "许嵩",
                    "albumName": "许嵩早期单曲集",
                    "mp3": "http://migu/m.mp3",
                    "flac": "http://migu/f.flac",
                    "id": "M1",
                }
            ]
        )
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data=payload)})
        patch_session("music_sync.sources.migu.get_session", stub)

        out = MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        assert out[0].quality == "flac"
        assert out[0].file_ext == "flac"
        assert out[0].download_url == "http://migu/f.flac"

    def test_falls_back_to_mp3(self, stub_session, patch_session, fake_response):
        payload = _payload(
            [{"songName": "断桥残雪", "singerName": "许嵩", "albumName": "", "mp3": "http://migu/m.mp3", "id": "M1"}]
        )
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data=payload)})
        patch_session("music_sync.sources.migu.get_session", stub)

        out = MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert out[0].quality == "320k"
        assert out[0].file_ext == "mp3"

    def test_accepts_sq_alias_for_flac(self, stub_session, patch_session, fake_response):
        payload = _payload(
            [{"songName": "断桥残雪", "singerName": "许嵩", "sq": "http://migu/sq.flac", "id": "M1"}]
        )
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data=payload)})
        patch_session("music_sync.sources.migu.get_session", stub)
        assert MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)[0].quality == "flac"

    def test_missing_url_yields_no_candidate(self, stub_session, patch_session, fake_response):
        payload = _payload([{"songName": "断桥残雪", "singerName": "许嵩", "id": "M1"}])
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data=payload)})
        patch_session("music_sync.sources.migu.get_session", stub)
        assert MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_artist_mismatch_filtered(self, stub_session, patch_session, fake_response):
        payload = _payload(
            [{"songName": "断桥残雪", "singerName": "沐萧", "mp3": "http://migu/m.mp3", "id": "M1"}]
        )
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data=payload)})
        patch_session("music_sync.sources.migu.get_session", stub)
        assert MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_blacklisted_title_filtered(self, stub_session, patch_session, fake_response):
        payload = _payload(
            [{"songName": "断桥残雪 (DJ版)", "singerName": "许嵩", "mp3": "http://migu/m.mp3", "id": "M1"}]
        )
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data=payload)})
        patch_session("music_sync.sources.migu.get_session", stub)
        assert MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(503, text="err")})
        patch_session("music_sync.sources.migu.get_session", stub)
        assert MiguMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
