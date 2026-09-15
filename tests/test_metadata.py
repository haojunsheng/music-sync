"""基准元数据（M1）测试。

M1 是整条流水线的锚点：它的 title/artist/duration 会被拿去搜索所有音源。
一旦这里取错歌，后面每个源都会搜错，所以匹配校验是重点回归对象。

基准源优先级：Apple Music（配了 token 且 priority=true）-> QQ 音乐 -> iTunes
-> MusicBrainz -> 网易云 -> Fallback。

Apple Music 只做元数据与封面锚点：完整音轨是 FairPlay DRM 的，拿不到音频流，
所以这里不测「下载」，只测「解析 + 匹配校验 + 优先级落位」。
"""
import json

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


APPLE_URL_KEY = "amp-api.music.apple.com"

# 真实接口返回的关键字段：durationInMillis 是毫秒（比 QQ 的 interval 秒级更准），
# artwork.url 是 `{w}x{h}bb.jpg` 模板，最长边可到 3000px 以上。
APPLE_ARTWORK_TMPL = "https://is1-ssl.mzstatic.com/image/thumb/Music221/v4/4c/8a/dj.jpg/{w}x{h}bb.jpg"


def _apple_song(
    name="断桥残雪",
    artist="许嵩",
    album="许嵩精选合辑",
    ms=227109,
    release="2007-05-01T07:00:00Z",
    artwork_url=APPLE_ARTWORK_TMPL,
):
    return {
        "id": "933793690",
        "type": "songs",
        "attributes": {
            "name": name,
            "artistName": artist,
            "albumName": album,
            "durationInMillis": ms,
            "releaseDate": release,
            "isrc": "HKE571433403",
            "artwork": {"url": artwork_url, "width": 3000, "height": 3000},
        },
    }


def _apple_resp(songs):
    return {"results": {"songs": {"href": "/v1/catalog/cn/search", "data": songs}}}


@pytest.fixture
def apple_config(isolate_config):
    """在隔离的配置目录里落一份带 Apple Music token 的 config.json。

    isolate_config 是 autouse 夹具，把 DEFAULT_CONFIG_FILE 重定向到 tmp_path，
    所以这里写的是假配置，绝不会碰到用户真实的 ~/.config/music-sync/。
    """

    def _write(token="fake-apple-token", storefront="cn", priority=True):
        isolate_config.mkdir(parents=True, exist_ok=True)
        (isolate_config / "config.json").write_text(
            json.dumps(
                {
                    "apple_music_token": token,
                    "apple_music_storefront": storefront,
                    "apple_music_priority": priority,
                }
            ),
            encoding="utf-8",
        )

    return _write


def _stub_all_sources(monkeypatch, **overrides):
    """把所有基准元数据源打桩为 None，可用 overrides 单独覆盖某个源。

    注意 Apple Music 的签名带第三个 cfg 形参（避免每首歌重读配置），
    overrides 里的替身也要接受 `cfg=None`。
    """
    for name in (
        "fetch_apple_music_metadata",
        "fetch_qq_metadata",
        "fetch_itunes_metadata",
        "fetch_musicbrainz_metadata",
        "fetch_netease_metadata",
    ):
        monkeypatch.setattr(metadata, name, overrides.get(name, _stub_no_metadata))


def _stub_no_metadata(title, artist, cfg=None):
    return None


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


def _apple_meta(cover="http://apple/c.jpg"):
    return metadata.OfficialMetadata(
        "断桥残雪", "许嵩", "许嵩精选合辑", 227, cover_url=cover, source="AppleMusic"
    )


def _qq_meta():
    return metadata.OfficialMetadata(
        "断桥残雪", "许嵩", "许嵩早期单曲集", 227, cover_url="http://qq/c.jpg", source="QQMusic"
    )


class TestAppleArtistOrder:
    """Apple 与 QQ 对合作歌手的排列常不一致，归档目录会跟着首位歌手跑。"""

    def test_preferred_artist_moved_to_front(self):
        assert metadata._reorder_artists("汪苏泷 & 徐良", "徐良") == "徐良/汪苏泷"

    def test_kept_when_preferred_already_first(self):
        assert metadata._reorder_artists("汪苏泷 & 徐良", "汪苏泷") == "汪苏泷 & 徐良"

    def test_kept_for_single_artist(self):
        assert metadata._reorder_artists("许嵩", "许嵩") == "许嵩"

    def test_kept_when_preferred_not_present(self):
        assert metadata._reorder_artists("汪苏泷 & 徐良", "许嵩") == "汪苏泷 & 徐良"

    def test_handles_multiple_separators(self):
        assert metadata._reorder_artists("A、B、C", "C") == "C/A/B"

    def test_blank_preferred_is_noop(self):
        assert metadata._reorder_artists("汪苏泷 & 徐良", "") == "汪苏泷 & 徐良"

    def test_blank_artist_name_is_noop(self):
        assert metadata._reorder_artists("", "徐良") == ""


class TestAppleMusicMetadata:
    def test_requires_token(self, stub_session, patch_session, fake_response):
        """没配 token 时直接跳过，且一个请求都不该发出去。"""
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song()]))})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None
        assert stub.calls == []

    def test_parses_song(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song()]))})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        assert meta is not None
        assert meta.title == "断桥残雪"
        assert meta.artist == "许嵩"
        assert meta.album == "许嵩精选合辑"
        assert meta.duration_seconds == 227  # 227109ms -> 227s
        assert meta.release_year == "2007"
        assert meta.source == "AppleMusic"

    def test_upgrades_artwork_resolution(self, stub_session, patch_session, fake_response, apple_config):
        """Apple 的封面模板最长边能到 3000px，不能原样留着 {w}x{h}。"""
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song()]))})
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        assert "{w}" not in meta.cover_url and "{h}" not in meta.cover_url
        assert "/1000x1000bb.jpg" in meta.cover_url

    def test_uses_configured_storefront(self, stub_session, patch_session, fake_response, apple_config):
        apple_config(storefront="jp")
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song()]))})
        patch_session("music_sync.metadata.get_session", stub)

        metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        assert "/v1/catalog/jp/search" in stub.calls[0][1]

    def test_sends_web_player_headers(self, stub_session, patch_session, fake_response, apple_config):
        """回归：AMPWebPlay 的 token 在 api.music.apple.com 上会被拒成 401，
        必须走 amp-api 域名并带 Origin/Referer，否则真实环境必然失败。"""
        apple_config(token="tok-123")
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song()]))})
        patch_session("music_sync.metadata.get_session", stub)

        metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        headers = stub.calls[0][2]["headers"]
        assert headers["Authorization"] == "Bearer tok-123"
        assert headers["Origin"] == "https://music.apple.com"
        assert "music.apple.com" in headers["Referer"]

    def test_requests_song_type(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song()]))})
        patch_session("music_sync.metadata.get_session", stub)

        metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        params = stub.calls[0][2]["params"]
        assert params["types"] == "songs"
        assert "断桥残雪" in params["term"] and "许嵩" in params["term"]

    def test_token_rejected_returns_none(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(401, text="unauthorized")})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_http_error_returns_none(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(500, text="boom")})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_non_json_response_returns_none(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, text="<html>not json</html>")})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_empty_result_returns_none(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([]))})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_skips_entry_without_duration(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song(ms=0)]))})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_live_version_is_blacklisted(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(
                200, _apple_resp([_apple_song(name="断桥残雪 (Live)", album="演唱会")])
            )
        })
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_artist_mismatch_is_skipped(self, stub_session, patch_session, fake_response, apple_config):
        """Apple 搜索结果里会混进别人的翻唱，歌手对不上时必须丢弃。"""
        apple_config()
        stub = stub_session({APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song(artist="沐萧")]))})
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("断桥残雪", "许嵩") is None

    def test_exact_title_preferred_over_suffixed(self, stub_session, patch_session, fake_response, apple_config):
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(200, _apple_resp([
                _apple_song(name="断桥残雪 (吉他版)", album="别人的专辑"),
                _apple_song(name="断桥残雪", album="许嵩精选合辑"),
            ]))
        })
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        assert meta.title == "断桥残雪"
        assert meta.album == "许嵩精选合辑"

    def test_strips_edition_suffix_when_base_matches_query(
        self, stub_session, patch_session, fake_response, apple_config
    ):
        """回归：Apple 把网剧出处写进曲名（真实案例），不归一化会让同一首歌
        在文件名里多一截 —— 上一轮下的 `后会无期.flac` 复用不上，白下一遍。"""
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(
                200,
                _apple_resp([
                    _apple_song(name="后会无期 (《诡案》网络剧插曲)", artist="汪苏泷 & 徐良", album="不良少年")
                ]),
            )
        })
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_apple_music_metadata("后会无期", "徐良")
        assert meta.title == "后会无期"
        # 专辑信息保持 Apple 原样，只把曲名收干净
        assert meta.album == "不良少年"

    def test_keeps_apple_title_when_base_differs(
        self, stub_session, patch_session, fake_response, apple_config
    ):
        """括注去掉后跟用户查询对不上，说明那是曲名的一部分，不能乱剪。"""
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(
                200, _apple_resp([_apple_song(name="后会无期 主题曲", artist="徐良")])
            )
        })
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("后会无期", "徐良").title == "后会无期 主题曲"

    def test_custom_query_with_brackets_is_not_stripped(
        self, stub_session, patch_session, fake_response, apple_config
    ):
        """用户自己就查带括注的版本时，必须保留原曲名，不能被归一化吃掉。"""
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song(name="断桥残雪 (吉他版)")]))
        })
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_apple_music_metadata("断桥残雪 (吉他版)", "许嵩")
        assert meta.title == "断桥残雪 (吉他版)"

    def test_preferred_artist_leads_the_collab_list(
        self, stub_session, patch_session, fake_response, apple_config
    ):
        """回归：查「徐良」的歌不该被归到 汪苏泷/ 目录下去，否则曲库里一份歌两处。"""
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(
                200, _apple_resp([_apple_song(name="后会无期", artist="汪苏泷 & 徐良", album="不良少年")])
            )
        })
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("后会无期", "徐良").artist == "徐良/汪苏泷"

    def test_collab_order_kept_when_query_is_first(
        self, stub_session, patch_session, fake_response, apple_config
    ):
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(
                200, _apple_resp([_apple_song(name="后会无期", artist="汪苏泷 & 徐良", album="不良少年")])
            )
        })
        patch_session("music_sync.metadata.get_session", stub)

        assert metadata.fetch_apple_music_metadata("后会无期", "汪苏泷").artist == "汪苏泷 & 徐良"

    def test_suffixed_title_used_when_nothing_exact(self, stub_session, patch_session, fake_response, apple_config):
        """没有完全同名版本时，退而用第一个通过校验的结果，而不是直接放弃。"""
        apple_config()
        stub = stub_session({
            APPLE_URL_KEY: fake_response(200, _apple_resp([_apple_song(name="断桥残雪 (吉他版)")]))
        })
        patch_session("music_sync.metadata.get_session", stub)

        meta = metadata.fetch_apple_music_metadata("断桥残雪", "许嵩")
        assert meta is not None
        assert meta.duration_seconds == 227


class TestAppleMusicPriority:
    def test_apple_is_first_when_token_and_priority(self, monkeypatch, apple_config):
        apple_config()
        _stub_all_sources(
            monkeypatch,
            fetch_apple_music_metadata=lambda t, a, cfg=None: _apple_meta(),
            fetch_qq_metadata=lambda t, a: pytest.fail("Apple 命中后不应再查 QQ"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "AppleMusic"

    def test_apple_not_consulted_without_token(self, monkeypatch):
        _stub_all_sources(
            monkeypatch,
            fetch_apple_music_metadata=lambda t, a, cfg=None: pytest.fail("没配 token 不该查 Apple Music"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "Fallback"

    def test_apple_miss_falls_through_to_qq(self, monkeypatch, apple_config):
        apple_config()
        _stub_all_sources(monkeypatch, fetch_qq_metadata=lambda t, a: _qq_meta())
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "QQMusic"

    def test_apple_demoted_below_qq_when_priority_off(self, monkeypatch, apple_config):
        apple_config(priority=False)
        _stub_all_sources(
            monkeypatch,
            fetch_apple_music_metadata=lambda t, a, cfg=None: pytest.fail(
                "priority=false 时 QQ 命中后不该再查 Apple Music"
            ),
            fetch_qq_metadata=lambda t, a: _qq_meta(),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "QQMusic"

    def test_apple_used_after_qq_miss_when_priority_off(self, monkeypatch, apple_config):
        """priority=false 只是降序，不是禁用：QQ 拿不到时 Apple 仍要兜住。"""
        apple_config(priority=False)
        _stub_all_sources(monkeypatch, fetch_apple_music_metadata=lambda t, a, cfg=None: _apple_meta())
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "AppleMusic"

    def test_apple_before_itunes_when_priority_off(self, monkeypatch, apple_config):
        apple_config(priority=False)
        _stub_all_sources(
            monkeypatch,
            fetch_apple_music_metadata=lambda t, a, cfg=None: _apple_meta(),
            fetch_itunes_metadata=lambda t, a: pytest.fail("Apple 排在 iTunes 之前"),
        )
        assert metadata.get_official_metadata("断桥残雪", "许嵩").source == "AppleMusic"

    def test_config_is_passed_down_to_avoid_rereading(self, monkeypatch, apple_config):
        """每首歌都 load_config() 一次太浪费，配置应透传进 fetch 函数。"""
        apple_config(storefront="jp")
        seen = {}

        def _capture(title, artist, cfg=None):
            seen["storefront"] = getattr(cfg, "apple_music_storefront", None)
            return None

        _stub_all_sources(monkeypatch, fetch_apple_music_metadata=_capture)
        metadata.get_official_metadata("断桥残雪", "许嵩")
        assert seen["storefront"] == "jp"


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
