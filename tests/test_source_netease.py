"""网易云音源测试。

接口说明：已废弃的 weapi 通道会返回 200 + 空 body；现行有效的是 eapi
（https://interface.music.163.com/eapi/...），且必须携带登录态 Cookie。
"""
import pytest

from music_sync import config as config_mod
from music_sync.sources.netease import NetEaseMusicSource

SEARCH_URL_KEY = "music.163.com/api/search/get/web"
EAPI_URL_KEY = "interface.music.163.com"


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


def _player(level, url, fee=1):
    return {"data": [{"url": url, "level": level, "fee": fee}]}


@pytest.fixture
def with_cookie():
    cfg = config_mod.load_config()
    cfg.netease_cookie = "MUSIC_U=token"
    config_mod.save_config(cfg)


class TestNeteaseDirectLink:
    def test_lossless_hit_reports_flac(self, with_cookie, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 27646693, "name": "断桥残雪", "artists": ["许嵩"], "album": "许嵩早期单曲集"}]
                )),
                EAPI_URL_KEY: fake_response(200, _player("lossless", "http://ne/song.flac")),
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

    def test_falls_back_to_exhigh_when_lossless_has_no_url(
        self, with_cookie, stub_session, patch_session, fake_response
    ):
        calls = {"n": 0}

        def handler(method, url, kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                # 第一次请求 lossless：无权限，url 为 null
                return fake_response(200, _player("standard", None))
            # 第二次请求 exhigh：拿到 320k
            return fake_response(200, _player("exhigh", "http://ne/song.mp3"))

        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                EAPI_URL_KEY: handler,
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)

        out = NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        assert out[0].quality == "320k"
        assert out[0].file_ext == "mp3"
        assert calls["n"] == 2

    def test_standard_level_is_reported_as_128k(
        self, with_cookie, stub_session, patch_session, fake_response
    ):
        """源如实上报实际音质，是否采用由上层策略决定。"""
        def handler(method, url, kwargs):
            return fake_response(200, _player("standard", "http://ne/low.mp3"))

        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                EAPI_URL_KEY: handler,
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        out = NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert out[0].quality == "128k"

    def test_no_url_at_all_returns_empty(self, with_cookie, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                EAPI_URL_KEY: fake_response(200, _player("standard", None)),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_eapi_non_json_response_is_handled(self, with_cookie, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                EAPI_URL_KEY: fake_response(200, text="<html>blocked</html>"),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_missing_cookie_still_attempts_and_reports(
        self, stub_session, patch_session, fake_response, capsys
    ):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["许嵩"]}]
                )),
                EAPI_URL_KEY: fake_response(200, _player("standard", None)),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        out = capsys.readouterr().out
        assert "netease_cookie" in out


class TestNeteaseFiltering:
    def test_artist_mismatch_filtered(self, with_cookie, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪", "artists": ["沐萧"]}]
                )),
                EAPI_URL_KEY: fake_response(200, _player("lossless", "http://ne/s.flac")),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_blacklisted_title_filtered(self, with_cookie, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, _search_payload(
                    [{"id": 1, "name": "断桥残雪 (Live)", "artists": ["许嵩"]}]
                )),
                EAPI_URL_KEY: fake_response(200, _player("lossless", "http://ne/s.flac")),
            }
        )
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []


class TestNeteaseSearchErrors:
    def test_search_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(500, text="err")})
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_search_non_json_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, text="<html>")})
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_empty_song_list_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, json_data={"result": {"songs": []}})})
        patch_session("music_sync.sources.netease.get_session", stub)
        assert NetEaseMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []
