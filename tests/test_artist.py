"""歌手热门歌曲获取测试。

策略：优先 QQ 音乐（华语曲库最全），定位失败或歌单为空时回退网易云。
"""
import pytest

from music_sync import artist as artist_mod

QQ_SEARCH_KEY = "c.y.qq.com/soso"
QQ_DETAIL_KEY = "u.y.qq.com/cgi-bin/musicu.fcg"
NE_SEARCH_KEY = "music.163.com/api/search/get/web"
NE_TOP_KEY = "music.163.com/api/artist/top/song"


def _qq_search(singers):
    return {"data": {"song": {"list": [{"singer": singers}]}}}


def _qq_songlist(items):
    return {"req": {"code": 0, "data": {"songlist": items}}}


def _qq_song(name, singers, album="", interval=227):
    return {
        "name": name,
        "singer": [{"name": s} for s in singers],
        "album": {"name": album},
        "interval": interval,
    }


def _ne_artists(items):
    return {"result": {"artists": items}}


def _ne_songs(items):
    return {"songs": items}


def _ne_song(name, artists, album="", dt_ms=227000):
    return {"name": name, "ar": [{"name": a} for a in artists], "al": {"name": album}, "dt": dt_ms}


class TestQqArtistSongs:
    def test_resolves_singer_mid_and_parses_songs(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "许嵩", "mid": "MID1"}])),
                QQ_DETAIL_KEY: fake_response(200, json_data=_qq_songlist([
                    _qq_song("素颜", ["许嵩", "何曼婷"], "素颜", 238),
                    _qq_song("幻听", ["许嵩"], "梦游计", 273),
                ])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)

        songs = artist_mod.get_artist_top_songs("许嵩", 50)
        assert songs == [
            {"title": "素颜", "artist": "许嵩/何曼婷", "album": "素颜", "duration": 238},
            {"title": "幻听", "artist": "许嵩", "album": "梦游计", "duration": 273},
        ]

    def test_exact_singer_name_wins_over_partial_match(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([
                    {"name": "不许嵩手", "mid": "WRONG"},
                    {"name": "许嵩", "mid": "RIGHT"},
                ])),
                QQ_DETAIL_KEY: fake_response(200, json_data=_qq_songlist([_qq_song("素颜", ["许嵩"])])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        artist_mod.get_artist_top_songs("许嵩", 50)

        detail_calls = [c for c in stub.calls if "musicu.fcg" in c[1]]
        assert detail_calls
        assert '"RIGHT"' in detail_calls[0][2].get("data", "")

    def test_limit_is_applied(self, stub_session, patch_session, fake_response):
        items = [_qq_song(f"歌{i}", ["许嵩"]) for i in range(10)]
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "许嵩", "mid": "MID1"}])),
                QQ_DETAIL_KEY: fake_response(200, json_data=_qq_songlist(items)),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        assert len(artist_mod.get_artist_top_songs("许嵩", 3)) == 3

    def test_entries_without_name_are_skipped(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "许嵩", "mid": "MID1"}])),
                QQ_DETAIL_KEY: fake_response(200, json_data=_qq_songlist([
                    {"singer": [{"name": "许嵩"}]},          # 没有歌名
                    _qq_song("幻听", ["许嵩"]),
                ])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        songs = artist_mod.get_artist_top_songs("许嵩", 50)
        assert [s["title"] for s in songs] == ["幻听"]


class TestNeteaseFallback:
    def test_falls_back_when_qq_cannot_locate_singer(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "完全不相干", "mid": "X"}])),
                NE_SEARCH_KEY: fake_response(200, json_data=_ne_artists([{"id": 5771, "name": "许嵩"}])),
                NE_TOP_KEY: fake_response(200, json_data=_ne_songs([_ne_song("幻听", ["许嵩"], "梦游计")])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)

        songs = artist_mod.get_artist_top_songs("许嵩", 50)
        assert songs == [{"title": "幻听", "artist": "许嵩", "album": "梦游计", "duration": 227}]

    def test_falls_back_when_qq_songlist_is_empty(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "许嵩", "mid": "MID1"}])),
                QQ_DETAIL_KEY: fake_response(200, json_data=_qq_songlist([])),
                NE_SEARCH_KEY: fake_response(200, json_data=_ne_artists([{"id": 5771, "name": "许嵩"}])),
                NE_TOP_KEY: fake_response(200, json_data=_ne_songs([_ne_song("素颜", ["许嵩"])])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        assert artist_mod.get_artist_top_songs("许嵩", 50)[0]["title"] == "素颜"

    def test_exact_artist_id_preferred(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "nobody", "mid": "X"}])),
                NE_SEARCH_KEY: fake_response(200, json_data=_ne_artists([
                    {"id": 999, "name": "许嵩粉丝团"},
                    {"id": 5771, "name": "许嵩"},
                ])),
                NE_TOP_KEY: fake_response(200, json_data=_ne_songs([_ne_song("幻听", ["许嵩"])])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        artist_mod.get_artist_top_songs("许嵩", 50)

        top_calls = [c for c in stub.calls if "artist/top/song" in c[1]]
        assert top_calls
        assert "5771" in str(top_calls[0][2])

    def test_limit_applied_for_netease(self, stub_session, patch_session, fake_response):
        items = [_ne_song(f"歌{i}", ["许嵩"]) for i in range(10)]
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "x", "mid": "X"}])),
                NE_SEARCH_KEY: fake_response(200, json_data=_ne_artists([{"id": 1, "name": "许嵩"}])),
                NE_TOP_KEY: fake_response(200, json_data=_ne_songs(items)),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        assert len(artist_mod.get_artist_top_songs("许嵩", 4)) == 4


class TestDegradation:
    def test_returns_empty_when_both_sources_fail(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(500, text="err"),
                NE_SEARCH_KEY: fake_response(500, text="err"),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        assert artist_mod.get_artist_top_songs("许嵩", 50) == []

    def test_limit_zero_short_circuits(self, stub_session, patch_session):
        class Exploding:
            def get(self, *a, **k):
                raise AssertionError("limit<=0 时不应发起请求")

            def post(self, *a, **k):
                raise AssertionError("limit<=0 时不应发起请求")

        patch_session("music_sync.artist.get_session", Exploding())
        assert artist_mod.get_artist_top_songs("许嵩", 0) == []

    def test_non_json_response_degrades_gracefully(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, text="<html>blocked</html>"),
                NE_SEARCH_KEY: fake_response(200, text="<html>blocked</html>"),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        assert artist_mod.get_artist_top_songs("许嵩", 50) == []

    def test_qq_detail_error_still_falls_back(self, stub_session, patch_session, fake_response):
        stub = stub_session(
            {
                QQ_SEARCH_KEY: fake_response(200, json_data=_qq_search([{"name": "许嵩", "mid": "MID1"}])),
                QQ_DETAIL_KEY: fake_response(200, json_data={"req": {"code": -1}}),
                NE_SEARCH_KEY: fake_response(200, json_data=_ne_artists([{"id": 5771, "name": "许嵩"}])),
                NE_TOP_KEY: fake_response(200, json_data=_ne_songs([_ne_song("素颜", ["许嵩"])])),
            }
        )
        patch_session("music_sync.artist.get_session", stub)
        assert artist_mod.get_artist_top_songs("许嵩", 50)[0]["title"] == "素颜"
