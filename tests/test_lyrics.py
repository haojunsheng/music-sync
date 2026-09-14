"""歌词模块测试：时间戳解析、双源回退链、与音频时长的一致性校验。"""
import base64

import pytest

from music_sync import lyrics


class TestParseLastLyricTimestamp:
    def test_returns_zero_when_no_timestamp(self):
        assert lyrics.parse_last_lyric_timestamp("没有任何时间戳") == 0.0

    def test_returns_zero_for_empty_string(self):
        assert lyrics.parse_last_lyric_timestamp("") == 0.0

    def test_parses_single_timestamp_with_decimals(self):
        assert lyrics.parse_last_lyric_timestamp("[00:10.50]你好") == pytest.approx(10.5)

    def test_parses_timestamp_without_decimals(self):
        assert lyrics.parse_last_lyric_timestamp("[01:20]你好") == pytest.approx(80.0)

    def test_returns_the_last_timestamp(self):
        text = "[00:01.00]第一句\n[01:00.00]第二句\n[03:15.25]最后一句\n"
        assert lyrics.parse_last_lyric_timestamp(text) == pytest.approx(3 * 60 + 15.25)


class TestFetchQqLyrics:
    def test_decodes_base64_payload(self, stub_session, patch_session, fake_response):
        raw = "[00:01.00]断桥残雪"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        stub = stub_session({"c.y.qq.com/lyric": fake_response(200, json_data={"lyric": encoded})})
        patch_session("music_sync.lyrics.get_session", stub)
        assert lyrics.fetch_qq_lyrics("MID1") == raw

    def test_missing_lyric_field_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({"c.y.qq.com/lyric": fake_response(200, json_data={})})
        patch_session("music_sync.lyrics.get_session", stub)
        assert lyrics.fetch_qq_lyrics("MID1") is None

    def test_http_error_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({"c.y.qq.com/lyric": fake_response(500, text="err")})
        patch_session("music_sync.lyrics.get_session", stub)
        assert lyrics.fetch_qq_lyrics("MID1") is None


class TestFetchNeteaseLyrics:
    def test_fetches_lyric_via_weapi(self, stub_session, patch_session, fake_response):
        search = {"result": {"songs": [{"id": 123}]}}
        lrc = {"lrc": {"lyric": "[00:01.00]hello"}}
        stub = stub_session(
            {
                "music.163.com/api/search/get/web": fake_response(200, json_data=search),
                "weapi/crypto/song/lyric": fake_response(200, json_data=lrc),
            }
        )
        patch_session("music_sync.lyrics.get_session", stub)
        assert lyrics.fetch_netease_lyrics("断桥残雪", "许嵩") == "[00:01.00]hello"

    def test_no_search_result_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {"music.163.com/api/search/get/web": fake_response(200, json_data={"result": {"songs": []}})}
        )
        patch_session("music_sync.lyrics.get_session", stub)
        assert lyrics.fetch_netease_lyrics("断桥残雪", "许嵩") is None

    def test_search_http_error_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({"music.163.com/api/search/get/web": fake_response(500, text="err")})
        patch_session("music_sync.lyrics.get_session", stub)
        assert lyrics.fetch_netease_lyrics("断桥残雪", "许嵩") is None


class TestGetLyricsFallbackChain:
    def test_prefers_qq_when_songmid_given(self, monkeypatch):
        monkeypatch.setattr(lyrics, "fetch_qq_lyrics", lambda mid: "[00:01.00]qq")
        monkeypatch.setattr(
            lyrics, "fetch_netease_lyrics", lambda t, a: pytest.fail("有 QQ 歌词时不应回退网易云")
        )
        lrc, ok = lyrics.get_lyrics("断桥残雪", "许嵩", qq_songmid="MID1")
        assert lrc == "[00:01.00]qq"
        assert ok is True

    def test_no_songmid_skips_qq(self, monkeypatch):
        called = {"qq": False}

        def fake_qq(mid):
            called["qq"] = True
            return "x"

        monkeypatch.setattr(lyrics, "fetch_qq_lyrics", fake_qq)
        monkeypatch.setattr(lyrics, "fetch_netease_lyrics", lambda t, a: "[00:01.00]ne")
        lyrics.get_lyrics("断桥残雪", "许嵩")
        assert called["qq"] is False

    def test_falls_back_to_netease_when_qq_fails(self, monkeypatch):
        monkeypatch.setattr(lyrics, "fetch_qq_lyrics", lambda mid: None)
        monkeypatch.setattr(lyrics, "fetch_netease_lyrics", lambda t, a: "[00:01.00]ne")
        lrc, ok = lyrics.get_lyrics("断桥残雪", "许嵩", qq_songmid="MID1")
        assert lrc == "[00:01.00]ne"
        assert ok is True

    def test_both_sources_fail(self, monkeypatch):
        monkeypatch.setattr(lyrics, "fetch_qq_lyrics", lambda mid: None)
        monkeypatch.setattr(lyrics, "fetch_netease_lyrics", lambda t, a: None)
        assert lyrics.get_lyrics("断桥残雪", "许嵩") == ("", False)


class TestLyricDurationConsistency:
    def test_timestamp_beyond_duration_marks_inconsistent(self, monkeypatch):
        # 歌词最后一句 6:40 = 400s，远超 227s 的音频
        monkeypatch.setattr(lyrics, "fetch_qq_lyrics", lambda mid: "")
        monkeypatch.setattr(lyrics, "fetch_netease_lyrics", lambda t, a: "[06:40.00]end")
        lrc, ok = lyrics.get_lyrics("断桥残雪", "许嵩", expected_duration=227)
        assert lrc == "[06:40.00]end"
        assert ok is False

    def test_timestamp_close_to_duration_is_consistent(self, monkeypatch):
        # 3:47 = 227s，与音频长度一致
        monkeypatch.setattr(lyrics, "fetch_qq_lyrics", lambda mid: "")
        monkeypatch.setattr(lyrics, "fetch_netease_lyrics", lambda t, a: "[03:47.00]end")
        _, ok = lyrics.get_lyrics("断桥残雪", "许嵩", expected_duration=227)
        assert ok is True

    def test_zero_expected_duration_skips_check(self, monkeypatch):
        monkeypatch.setattr(lyrics, "fetch_netease_lyrics", lambda t, a: "[99:00.00]end")
        _, ok = lyrics.get_lyrics("断桥残雪", "许嵩", expected_duration=0)
        assert ok is True
