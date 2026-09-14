"""酷狗音源测试。

回归点：playInfo 老接口对 VIP/付费曲目返回 url=""，
搜索能命中但拿不到直链，应返回空且不抛错。
"""
import pytest

from music_sync.sources.kugou import KugouMusicSource

SEARCH_URL_KEY = "mobilecdn.kugou.com/api/v3/search/song"
PLAY_URL_KEY = "m.kugou.com/app/i/getSongInfo.php"


def _search_payload(items):
    return {
        "data": {
            "info": [
                {
                    "songname": i["name"],
                    "singername": i["singer"],
                    "album_name": i.get("album", ""),
                    "duration": i.get("duration", 227),
                    "sqhash": i.get("sqhash", ""),
                    "320hash": i.get("320hash", ""),
                    "hash": i.get("hash", "PLAINHASH"),
                }
                for i in items
            ]
        }
    }


class TestKugouParsing:
    def test_hits_flac_when_extname_is_flac(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "许嵩", "album": "许嵩早期单曲集", "sqhash": "SQ1"}]
                )),
                PLAY_URL_KEY: fake_response(200, json_data={"url": "http://kugou/a.flac", "extName": "flac"}),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)

        out = KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "kugou"
        assert cand.song_id == "SQ1"
        assert cand.title == "断桥残雪"
        assert cand.artist == "许嵩"
        assert cand.quality == "flac"
        assert cand.file_ext == "flac"
        assert cand.download_url == "http://kugou/a.flac"

    def test_mp3_extname_reports_320k(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "许嵩", "320hash": "H320"}]
                )),
                PLAY_URL_KEY: fake_response(200, json_data={"url": "http://kugou/a.mp3", "extName": "mp3"}),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        out = KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert out[0].quality == "320k"

    def test_regression_empty_url_returns_empty(self, stub_session, patch_session, fake_response):
        """回归：VIP 曲目 playInfo 返回 url="" 时不得产出候选（也不得抛错）。"""
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "许嵩", "sqhash": "SQ1"}]
                )),
                PLAY_URL_KEY: fake_response(200, json_data={"url": "", "extName": ""}),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_artist_mismatch_filtered(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "沐萧", "sqhash": "SQ1"}]
                )),
                PLAY_URL_KEY: fake_response(200, json_data={"url": "http://kugou/a.flac", "extName": "flac"}),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_duration_mismatch_filtered(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "许嵩", "duration": 30, "sqhash": "SQ1"}]
                )),
                PLAY_URL_KEY: fake_response(200, json_data={"url": "http://kugou/a.flac", "extName": "flac"}),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_blacklisted_title_filtered(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪 (DJ版)", "singer": "许嵩", "sqhash": "SQ1"}]
                )),
                PLAY_URL_KEY: fake_response(200, json_data={"url": "http://kugou/a.flac", "extName": "flac"}),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_no_hash_yields_no_candidate(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "许嵩", "sqhash": "", "320hash": "", "hash": ""}]
                )),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_playinfo_non_json_does_not_crash(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"name": "断桥残雪", "singer": "许嵩", "sqhash": "SQ1"}]
                )),
                PLAY_URL_KEY: fake_response(200, text="<html>blocked</html>"),
            }
        )
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_search_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(500, text="err")})
        patch_session("music_sync.sources.kugou.get_session", stub)
        assert KugouMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
