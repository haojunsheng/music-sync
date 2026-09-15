"""基准元数据（M1）测试。

M1 是整条流水线的锚点：它的 title/artist/duration 会被拿去搜索所有音源。
一旦这里取错歌，后面每个源都会搜错，所以匹配校验是重点回归对象。

基准源优先级：QQ 音乐 -> iTunes -> MusicBrainz -> 网易云 -> Fallback。
"""
import pytest

from music_sync import metadata

ITUNES_RESP = {
    "results": [
        {
            "trackName": "断桥残雪",
            "artistName": "许嵩",
            "collectionName": "许嵩早期单曲集",
            "trackTimeMillis": 227000,
            "artworkUrl100": "https://p1.music.126.net/x/100x100bb.jpg",
            "releaseDate": "2009-01-01T00:00:00Z",
        }
    ]
}

MB_RESP = {
    "recordings": [
        {
            "title": "断桥残雪",
            "length": 227000,
            "releases": [{"title": "许嵩早期单曲集", "date": "2009-01-01"}],
            "artist-credit": [{"name": "许嵩"}],
        }
    ]
}

NE_MATCH_RESP = {
    "result": {
        "songs": [
            {
                "id": 27646693,
                "name": "断桥残雪",
                "artists": [{"name": "许嵩"}],
                "album": {"name": "许嵩早期单曲集", "picUrl": "https://p1.music.126.net/cover.jpg"},
                "duration": 227160,
            }
        ]
    }
}

QQ_URL_KEY = "c.y.qq.com/soso"

QQ_SEARCH_RESP = {
    "data": {
        "song": {
            "list": [
                {
                    "songname": "断桥残雪",
                    "singer": [{"name": "许嵩"}],
                    "albumname": "许嵩早期单曲集",
                    "albummid": "001jmC6x1RMfh0",
                    "interval": 227,
                    "pubtime": 1180713600,
                    "songmid": "004ENQPZ0dHaqy",
                }
            ]
        }
    }
}


def _song(name="断桥残雪", singer="许嵩", album="", albummid="", interval=227, pubtime=0):
    return {
        "songname": name,
        "singer": [{"name": singer}],
        "albumname": album,
        "albummid": albummid,
        "interval": interval,
        "pubtime": pubtime,
    }


def _qq_resp(songs):
    return {"data": {"song": {"list": songs}}}


def _stub_all_sources(monkeypatch, **overrides):
    """把所有基准元数据源打桩为 None，可用 overrides 单独覆盖某个源。"""
    for name in (
        "fetch_qq_metadata",
        "fetch_itunes_metadata",
        "fetch_musicbrainz_metadata",
        "fetch_netease_metadata",
    ):
        monkeypatch.setattr(metadata, name, overrides.get(name, lambda t, a: None))


class TestQqMetadata:
    def test_parses_song(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, QQ_SEARCH_RESP)})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_qq_metadata("断桥残雪", "许嵩")
        assert meta is not None
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.album == "许嵩早期单曲集"
        assert meta.duration_seconds == 227
        assert meta.source == "QQMusic"

    def test_builds_cover_url_from_albummid(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, QQ_SEARCH_RESP)})
        patch_session("music_sync.metadata.get_session", stub)
        meta = metadata.fetch_qq_metadata("断桥残雪", "许嵩")
        assert meta.cover_url == "https://y.gtimg.cn/music/photo_new/T002R300x300M000001jmC6x1RMfh0.jpg"

    def test_release_year_comes_from_pubtime(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, QQ_SEARCH_RESP)})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩").release_year == "2007"

    def test_missing_albummid_and_pubtime_yield_empty_fields(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, _qq_resp([_song(albummid="", pubtime=0)]))})
        patch_session("music_sync.metadata.get_session", stub)
        meta = metadata.fetch_qq_metadata("断桥残雪", "许嵩")
        assert meta.cover_url == ""
        assert meta.release_year == ""

    def test_regression_skips_unrelated_first_hit(self, stub_session, patch_session, fake_response):
        """回归：模糊搜索首条可能不是目标曲目，不能盲取 list[0]。"""
        stub = stub_session({QQ_URL_KEY: fake_response(200, _qq_resp([
            _song(name="幻听", album="梦游计", interval=273),
            _song(name="断桥残雪", album="许嵩早期单曲集", interval=227),
        ]))})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_qq_metadata("断桥残雪", "许嵩")
        assert meta.title == "断桥残雪"
        assert meta.duration_seconds == 227

    def test_live_version_is_blacklisted(self, stub_session, patch_session, fake_response):
        """Live 版时长与录音室版不同，不能拿来锚定基准。"""
        stub = stub_session({QQ_URL_KEY: fake_response(200, _qq_resp([
            _song(name="断桥残雪 (Live)", album="演唱会", interval=238),
            _song(name="断桥残雪", album="许嵩早期单曲集", interval=227),
        ]))})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩").duration_seconds == 227

    def test_exact_title_preferred_over_suffixed(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, _qq_resp([
            _song(name="断桥残雪 (电影版)", interval=230),
            _song(name="断桥残雪", interval=227),
        ]))})
        patch_session("music_sync.metadata.get_session", stub)
        meta = metadata.fetch_qq_metadata("断桥残雪", "许嵩")
        assert meta.title == "断桥残雪"
        assert meta.duration_seconds == 227

    def test_skips_entry_without_interval(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, _qq_resp([_song(interval=0)]))})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩") is None

    def test_artist_mismatch_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, _qq_resp([_song(singer="沐萧")]))})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩") is None

    def test_empty_list_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, json_data=_qq_resp([]))})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩") is None

    def test_http_error_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(500, text="err")})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩") is None

    def test_non_json_response_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({QQ_URL_KEY: fake_response(200, text="<html>blocked</html>")})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩") is None

    def test_multiple_singers_joined(self, stub_session, patch_session, fake_response):
        resp = _qq_resp([
            {"songname": "断桥残雪", "singer": [{"name": "许嵩"}, {"name": "何曼婷"}],
             "albumname": "", "albummid": "", "interval": 227, "pubtime": 0}
        ])
        stub = stub_session({QQ_URL_KEY: fake_response(200, resp)})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_qq_metadata("断桥残雪", "许嵩").artist == "许嵩/何曼婷"


class TestItunesMetadata:
    def test_parses_song(self, stub_session, patch_session, fake_response):
        stub = stub_session({"itunes.apple.com/search": fake_response(200, ITUNES_RESP)})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_itunes_metadata("断桥残雪", "许嵩")
        assert meta is not None
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.album == "许嵩早期单曲集"
        assert meta.duration_seconds == 227
        assert meta.source.startswith("iTunes")

    def test_upgrades_artwork_resolution_to_600(self, stub_session, patch_session, fake_response):
        stub = stub_session({"itunes.apple.com/search": fake_response(200, ITUNES_RESP)})
        patch_session("music_sync.metadata.get_session", stub)
        meta = metadata.fetch_itunes_metadata("断桥残雪", "许嵩")
        assert "600x600bb.jpg" in meta.cover_url
        assert "100x100" not in meta.cover_url

    def test_ignores_non_matching_result(self, stub_session, patch_session, fake_response):
        resp = {"results": [{"trackName": "完全无关的歌", "artistName": "别人", "trackTimeMillis": 1000}]}
        stub = stub_session({"itunes.apple.com/search": fake_response(200, resp)})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_itunes_metadata("断桥残雪", "许嵩") is None

    def test_returns_none_on_http_error(self, stub_session, patch_session, fake_response):
        stub = stub_session({"itunes.apple.com/search": fake_response(500, text="err")})
        patch_session("music_sync.metadata.get_session", stub)
        assert metadata.fetch_itunes_metadata("断桥残雪", "许嵩") is None


class TestMusicBrainzMetadata:
    def test_parses_recording(self, stub_session, patch_session, fake_response):
        stub = stub_session({"musicbrainz.org/ws/2/recording": fake_response(200, MB_RESP)})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_musicbrainz_metadata("断桥残雪", "许嵩")
        assert meta is not None
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.duration_seconds == 227
        assert meta.album == "许嵩早期单曲集"
        assert meta.release_year == "2009"
        assert meta.source == "MusicBrainz"

    def test_skips_recording_without_length(self, stub_session, patch_session, fake_response):
        resp = {"recordings": [{"title": "断桥残雪", "length": 0, "releases": [], "artist-credit": []}]}
        stub = stub_session({"musicbrainz.org/ws/2/recording": fake_response(200, resp)})
        patch_session("music_sync.metadata.get_session", stub)
        # duration 为 0 的记录不可用，应返回 None 而不是 0 秒的元数据
        assert metadata.fetch_musicbrainz_metadata("断桥残雪", "许嵩") is None


class TestNeteaseMetadata:
    def test_parses_song(self, stub_session, patch_session, fake_response):
        stub = stub_session({"music.163.com/api/search/get/web": fake_response(200, NE_MATCH_RESP)})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_netease_metadata("断桥残雪", "许嵩")
        assert meta is not None
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.duration_seconds == 227
        assert meta.source == "NetEase"

    def test_regression_skips_unrelated_first_hit(self, stub_session, patch_session, fake_response):
        """回归：网易云模糊搜索首条常与目标无关，不能盲取 songs[0]。

        实测「断桥残雪 - 沐萧」曾被错配成「知不知道 - NOTTIBO1」，污染全链路。
        """
        resp = {
            "result": {
                "songs": [
                    {
                        "id": 1,
                        "name": "知不知道",
                        "artists": [{"name": "NOTTIBO1/kill bad feelings"}],
                        "album": {"name": "x"},
                        "duration": 184000,
                    },
                    {
                        "id": 2,
                        "name": "断桥残雪",
                        "artists": [{"name": "沐萧"}],
                        "album": {"name": "我想牵着你的手"},
                        "duration": 227000,
                    },
                ]
            }
        }
        stub = stub_session({"music.163.com/api/search/get/web": fake_response(200, resp)})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_netease_metadata("断桥残雪", "沐萧")
        assert meta is not None
        assert meta.title == "断桥残雪"
        assert meta.artist == "沐萧"
        assert meta.duration_seconds == 227

    def test_regression_returns_none_when_nothing_matches(self, stub_session, patch_session, fake_response):
        resp = {
            "result": {
                "songs": [
                    {
                        "id": 1,
                        "name": "知不知道",
                        "artists": [{"name": "NOTTIBO1"}],
                        "album": {"name": "x"},
                        "duration": 184000,
                    }
                ]
            }
        }
        stub = stub_session({"music.163.com/api/search/get/web": fake_response(200, resp)})
        patch_session("music_sync.metadata.get_session", stub)
        # 关键：宁可不给元数据，也不能返回一首无关的歌
        assert metadata.fetch_netease_metadata("断桥残雪", "沐萧") is None


class TestGetOfficialMetadataPriority:
    def test_fallback_preserves_user_input(self, monkeypatch):
        _stub_all_sources(monkeypatch)
        meta = metadata.get_official_metadata("断桥残雪", "许嵩")
        assert meta.source == "Fallback"
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.duration_seconds == 0

    def test_qq_is_the_primary_source(self, monkeypatch):
        """回归：基准元数据首选 QQ 音乐，命中后不应再查其它源。"""
        qq = metadata.OfficialMetadata(
            "断桥残雪", "许嵩", "许嵩早期单曲集", 227, cover_url="http://qq/c.jpg", source="QQMusic"
        )
        _stub_all_sources(monkeypatch, fetch_qq_metadata=lambda t, a: qq)
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "QQMusic"

    def test_qq_hit_does_not_consult_lower_priority_sources(self, monkeypatch):
        qq = metadata.OfficialMetadata("断桥残雪", "许嵩", "", 227, cover_url="http://qq/c.jpg", source="QQMusic")
        _stub_all_sources(
            monkeypatch,
            fetch_qq_metadata=lambda t, a: qq,
            fetch_itunes_metadata=lambda t, a: pytest.fail("QQ 命中后不应再查 iTunes"),
            fetch_musicbrainz_metadata=lambda t, a: pytest.fail("QQ 命中后不应再查 MusicBrainz"),
            fetch_netease_metadata=lambda t, a: pytest.fail("QQ 命中后不应再查网易云"),
        )
        metadata.get_official_metadata("断桥残雪", "许嵩")

    def test_qq_without_duration_falls_through_to_itunes(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_qq_metadata=lambda t, a: metadata.OfficialMetadata("断桥残雪", "许嵩", "", 0, source="QQMusic"),
            fetch_itunes_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, source="iTunes (CN)"
            ),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "iTunes (CN)"

    def test_qq_without_cover_backfills_from_itunes(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_qq_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, cover_url="", source="QQMusic"
            ),
            fetch_itunes_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, cover_url="http://itunes/c.jpg", source="iTunes (CN)"
            ),
        )
        meta = metadata.get_official_metadata("断桥残雪", "许嵩")
        assert meta.cover_url == "http://itunes/c.jpg"
        assert meta.source == "QQMusic"

    def test_itunes_used_when_qq_misses(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_itunes_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "A", 227, source="iTunes (CN)"
            ),
            fetch_musicbrainz_metadata=lambda t, a: pytest.fail("iTunes 命中后不应再查 MusicBrainz"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "iTunes (CN)"

    def test_itunes_without_duration_falls_through_to_musicbrainz(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_itunes_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 0, source="iTunes (CN)"
            ),
            fetch_musicbrainz_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, source="MusicBrainz"
            ),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "MusicBrainz"

    def test_netease_used_only_when_others_fail(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_netease_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, source="NetEase"
            ),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "NetEase"

    def test_musicbrainz_without_cover_backfills_from_netease(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_musicbrainz_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, cover_url="", source="MusicBrainz"
            ),
            fetch_netease_metadata=lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, cover_url="http://cover", source="NetEase"
            ),
        )
        meta = metadata.get_official_metadata("断桥残雪", "许嵩")
        assert meta.cover_url == "http://cover"
        assert meta.source == "MusicBrainz"
