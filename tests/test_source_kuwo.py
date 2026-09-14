"""酷我音源测试。

核心回归点：`search.kuwo.cn/r.s` 返回的是**单引号包裹的 Python 字面量**，
不是标准 JSON。历史实现用 resp.json() 解析必然抛异常并被静默吞掉，
导致该源在任何情况下都返回空。这里把"单引号也能解析"钉死。
"""
import pytest

from music_sync.sources.kuwo import KuwoMusicSource

SEARCH_URL_KEY = "search.kuwo.cn/r.s"
PLAY_URL_KEY = "antiserver.kuwo.cn/anti.s"


def sq(value) -> str:
    """把值包成 Python 单引号字符串，模拟酷我老接口的响应格式。"""
    return "'" + str(value) + "'"


def kuwo_body(records) -> str:
    """构造酷我风格的响应体（单引号包裹，json.loads 无法解析）。"""
    items = ",".join(
        "{'SONGNAME':%s,'ARTIST':%s,'ALBUM':%s,'MUSICRID':%s,'DURATION':%s}"
        % (
            sq(r["name"]),
            sq(r["artist"]),
            sq(r.get("album", "")),
            sq(r["rid"]),
            sq(r.get("duration", 0)),
        )
        for r in records
    )
    return "{'abslist':[" + items + "]}"


class TestKuwoParsing:
    def test_regression_single_quote_payload_is_parsed(self, stub_session, patch_session, fake_response):
        """回归：单引号响应必须能被解析出候选（旧实现此处永远返回空）。"""
        body = kuwo_body(
            [{"name": "断桥残雪", "artist": "许嵩", "album": "许嵩早期单曲集", "rid": "MUSIC_123", "duration": 227}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="http://kw.example.com/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)

        out = KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "kuwo"
        assert cand.song_id == "123"  # MUSIC_ 前缀被剥离
        assert cand.title == "断桥残雪"
        assert cand.artist == "许嵩"
        assert cand.quality == "320k"
        assert cand.file_ext == "mp3"
        assert cand.download_url == "http://kw.example.com/a.mp3"

    def test_standard_json_payload_also_works(self, stub_session, patch_session, fake_response):
        payload = {
            "abslist": [
                {"SONGNAME": "断桥残雪", "ARTIST": "许嵩", "ALBUM": "", "MUSICRID": "MUSIC_123", "DURATION": "227"}
            ]
        }
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, json_data=payload),
                PLAY_URL_KEY: fake_response(200, text="http://kw.example.com/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert len(KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)) == 1

    def test_unparsable_body_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, text="<html>totally broken</html>")})
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_http_error_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(500, text="err")})
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_empty_abslist_returns_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session({SEARCH_URL_KEY: fake_response(200, text="{'abslist':[]}")})
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []


class TestKuwoFiltering:
    def test_nbsp_is_cleaned_before_blacklist(self, stub_session, patch_session, fake_response):
        body = kuwo_body(
            [
                {
                    "name": "断桥残雪&nbsp;(Live)",
                    "artist": "许嵩",
                    "album": "",
                    "rid": "MUSIC_1",
                    "duration": 227,
                }
            ]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="http://kw/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_artist_mismatch_filtered(self, stub_session, patch_session, fake_response):
        body = kuwo_body(
            [{"name": "断桥残雪", "artist": "创欣聆空", "album": "", "rid": "MUSIC_9", "duration": 227}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="http://kw/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)
        # 目标歌手是许嵩，翻唱者必须被过滤
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_duration_mismatch_filtered(self, stub_session, patch_session, fake_response):
        body = kuwo_body(
            [{"name": "断桥残雪", "artist": "许嵩", "album": "", "rid": "MUSIC_9", "duration": 100}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="http://kw/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_title_mismatch_filtered(self, stub_session, patch_session, fake_response):
        body = kuwo_body(
            [{"name": "别咬我", "artist": "许嵩", "album": "", "rid": "MUSIC_9", "duration": 227}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="http://kw/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []


class TestKuwoPlayUrl:
    def test_non_http_play_response_yields_no_candidate(self, stub_session, patch_session, fake_response):
        body = kuwo_body(
            [{"name": "断桥残雪", "artist": "许嵩", "album": "", "rid": "MUSIC_1", "duration": 227}]
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="error: not authorized"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)
        assert KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227) == []


class TestKuwoEscaping:
    def test_double_backslash_unicode_escape_is_restored(self, stub_session, patch_session, fake_response):
        """酷我把 & 转义成字面量 \\u0026（经 literal_eval 后仍残留一个反斜杠），需还原。"""
        # Python 源码里 "\\\\u0026" -> 实际文本两个反斜杠 + u0026，等价于接口原始返回
        artist_raw = "许嵩\\\\u0026Kent王健"
        body = (
            "{'abslist':[{'SONGNAME':'断桥残雪','ARTIST':'%s','ALBUM':'','MUSICRID':'MUSIC_1','DURATION':'227'}]}"
            % artist_raw
        )
        stub = stub_session(
            {
                SEARCH_URL_KEY: fake_response(200, text=body),
                PLAY_URL_KEY: fake_response(200, text="http://kw/a.mp3"),
            }
        )
        patch_session("music_sync.sources.kuwo.get_session", stub)

        out = KuwoMusicSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        # \u0026 被还原成 &，歌手里能正确识别出许嵩
        assert "&" in out[0].artist
        assert "\\u0026" not in out[0].artist
