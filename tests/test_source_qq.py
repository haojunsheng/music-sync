"""QQ 音源测试。

两个关键回归点：
1. 必须做歌名/歌手匹配校验 —— 否则会把免费的翻唱《断桥残雪 (柔情版) - 沐萧》
   当成许嵩原唱返回。
2. 未登录（无 qq_cookie）时 VIP 曲目拿不到任何 purl，应返回空而不是抛错。
"""
import pytest

from music_sync.sources.qq import QQMusicSource

SEARCH_URL_KEY = "c.y.qq.com/soso/fcgi-bin/client_search_cp"
VKEY_URL_KEY = "u.y.qq.com/cgi-bin/musicu.fcg"


def _search_payload(songs):
    return {
        "data": {
            "song": {
                "list": [
                    {
                        "songname": s["name"],
                        "singer": [{"name": name} for name in s["singer"]],
                        "albumname": s.get("album", ""),
                        "interval": s.get("interval", 0),
                        "songmid": s["mid"],
                    }
                    for s in songs
                ]
            }
        }
    }


def _vkey_payload(purl, sip="http://dl.stream.qqmusic.qq.com/"):
    return {"req_1": {"data": {"midurlinfo": [{"purl": purl}], "sip": [sip] if sip else []}}}


class TestQQSearchAndResolve:
    def test_hits_and_builds_download_url(self, stub_session, patch_session, fake_response):
        search = _search_payload(
            [{"name": "断桥残雪", "singer": ["许嵩"], "album": "许嵩早期单曲集", "interval": 227, "mid": "MID1"}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("F000MID1.flac?vkey=abc")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        out = QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "qq"
        assert cand.song_id == "MID1"
        assert cand.title == "断桥残雪"
        assert cand.artist == "许嵩"
        assert cand.file_ext == "flac"
        assert cand.quality == "flac"
        assert cand.download_url == "http://dl.stream.qqmusic.qq.com/F000MID1.flac?vkey=abc"

    def test_prefers_flac_over_lossy_when_all_available(self, stub_session, patch_session, fake_response):
        search = _search_payload([{"name": "断桥残雪", "singer": ["许嵩"], "interval": 227, "mid": "MID1"}])
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("any.mp3?vkey=abc")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        out = QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        # 格式按 F000->A000->M800->M500 顺序试探，先命中的是最高音质
        assert out[0].quality == "flac"

    def test_falls_back_to_128k_when_only_lossy_available(self, stub_session, patch_session, fake_response):
        """未登录时 VIP 曲目只有 128k 试听直链可用。"""

        def vkey_handler(method, url, kwargs):
            body = kwargs.get("data", "")
            purl = "M500MID1.mp3?vkey=abc" if "M500" in body else ""
            return fake_response(200, _vkey_payload(purl))

        search = _search_payload([{"name": "断桥残雪", "singer": ["许嵩"], "interval": 227, "mid": "MID1"}])
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, search), VKEY_URL_KEY: vkey_handler})
        patch_session("music_sync.sources.qq.get_session", stub)

        out = QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        assert out[0].quality == "128k"
        assert out[0].file_ext == "mp3"

    def test_regression_cover_version_is_filtered_out(self, stub_session, patch_session, fake_response):
        """回归：免费翻唱曾被当成原唱返回。歌手不一致时必须过滤。"""
        search = _search_payload(
            [{"name": "断桥残雪 (柔情版)", "singer": ["沐萧"], "album": "我想牵着你的手", "interval": 227, "mid": "COVER1"}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("M500COVER1.mp3?vkey=abc")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        assert QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_vip_track_without_any_purl_returns_empty(self, stub_session, patch_session, fake_response):
        search = _search_payload([{"name": "断桥残雪", "singer": ["许嵩"], "interval": 227, "mid": "MID1"}])
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        assert QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_blacklisted_version_is_filtered(self, stub_session, patch_session, fake_response):
        search = _search_payload([{"name": "断桥残雪 (Live)", "singer": ["许嵩"], "interval": 227, "mid": "LIVE1"}])
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("M500LIVE1.mp3?vkey=abc")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        assert QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_duration_mismatch_is_filtered(self, stub_session, patch_session, fake_response):
        search = _search_payload([{"name": "断桥残雪", "singer": ["许嵩"], "interval": 120, "mid": "MID1"}])
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("M500MID1.mp3?vkey=abc")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        assert QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_multiple_matching_songs_all_returned(self, stub_session, patch_session, fake_response):
        search = _search_payload(
            [
                {"name": "断桥残雪", "singer": ["许嵩"], "interval": 227, "mid": "A"},
                {"name": "断桥残雪", "singer": ["许嵩"], "interval": 228, "mid": "B"},
            ]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, search),
                VKEY_URL_KEY: fake_response(200, _vkey_payload("ok.mp3?vkey=abc")),
            }
        )
        patch_session("music_sync.sources.qq.get_session", stub)

        out = QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert {c.song_id for c in out} == {"A", "B"}

    def test_search_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(500, text="boom")})
        patch_session("music_sync.sources.qq.get_session", stub)
        assert QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_vkey_exception_does_not_break_whole_search(self, stub_session, patch_session, fake_response):
        def boom(method, url, kwargs):
            raise RuntimeError("network exploded")

        search = _search_payload([{"name": "断桥残雪", "singer": ["许嵩"], "interval": 227, "mid": "MID1"}])
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, search), VKEY_URL_KEY: boom})
        patch_session("music_sync.sources.qq.get_session", stub)

        # 单个 vkey 请求异常不应导致整个源崩溃
        assert QQMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []


class TestQQCookieParsing:
    def test_parse_cookie_dict(self):
        src = QQMusicSource()
        assert src._parse_cookie("uin=123456; qm_keyst=abc") == {"uin": "123456", "qm_keyst": "abc"}

    def test_parse_empty_cookie(self):
        assert QQMusicSource()._parse_cookie("") == {}
