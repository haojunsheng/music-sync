"""基准元数据（M1）测试。

M1 是整条流水线的锚点：它的 title/artist/duration 会被拿去搜索所有音源。
一旦这里取错歌，后面每个源都会搜错，所以匹配校验是重点回归对象。
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
        monkeypatch.setattr(metadata, "fetch_itunes_metadata", lambda t, a: None)
        monkeypatch.setattr(metadata, "fetch_musicbrainz_metadata", lambda t, a: None)
        monkeypatch.setattr(metadata, "fetch_netease_metadata", lambda t, a: None)

        meta = metadata.get_official_metadata("断桥残雪", "许嵩")
        assert meta.source == "Fallback"
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.duration_seconds == 0

    def test_itunes_takes_precedence(self, monkeypatch):
        itunes = metadata.OfficialMetadata("断桥残雪", "许嵩", "A", 227, source="iTunes (CN)")
        monkeypatch.setattr(metadata, "fetch_itunes_metadata", lambda t, a: itunes)
        monkeypatch.setattr(
            metadata,
            "fetch_musicbrainz_metadata",
            lambda t, a: pytest.fail("iTunes 命中后不应再查 MusicBrainz"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "iTunes (CN)"

    def test_itunes_without_duration_falls_through_to_musicbrainz(self, monkeypatch):
        monkeypatch.setattr(
            metadata,
            "fetch_itunes_metadata",
            lambda t, a: metadata.OfficialMetadata("断桥残雪", "许嵩", "", 0, source="iTunes (CN)"),
        )
        monkeypatch.setattr(
            metadata,
            "fetch_musicbrainz_metadata",
            lambda t, a: metadata.OfficialMetadata("断桥残雪", "许嵩", "", 227, source="MusicBrainz"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "MusicBrainz"

    def test_netease_used_only_when_others_fail(self, monkeypatch):
        monkeypatch.setattr(metadata, "fetch_itunes_metadata", lambda t, a: None)
        monkeypatch.setattr(metadata, "fetch_musicbrainz_metadata", lambda t, a: None)
        monkeypatch.setattr(
            metadata,
            "fetch_netease_metadata",
            lambda t, a: metadata.OfficialMetadata("断桥残雪", "许嵩", "", 227, source="NetEase"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "NetEase"

    def test_musicbrainz_without_cover_backfills_from_netease(self, monkeypatch):
        mb = metadata.OfficialMetadata("断桥残雪", "许嵩", "", 227, cover_url="", source="MusicBrainz")
        monkeypatch.setattr(metadata, "fetch_itunes_metadata", lambda t, a: None)
        monkeypatch.setattr(metadata, "fetch_musicbrainz_metadata", lambda t, a: mb)
        monkeypatch.setattr(
            metadata,
            "fetch_netease_metadata",
            lambda t, a: metadata.OfficialMetadata(
                "断桥残雪", "许嵩", "", 227, cover_url="http://cover", source="NetEase"
            ),
        )
        meta = metadata.get_official_metadata("断桥残雪", "许嵩")
        assert meta.cover_url == "http://cover"
        assert meta.source == "MusicBrainz"
