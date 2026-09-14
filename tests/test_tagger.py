"""标签写入模块测试：封面下载、格式分支、写入失败与回读校验。

真实音频文件的字节级写入依赖具体容器格式，这里聚焦路由逻辑与错误处理，
用打桩替换 write_flac_tags / write_mp3_tags / mutagen.File。
"""
import pytest

from music_sync import tagger


class TestDownloadCover:
    def test_empty_url_returns_none(self):
        assert tagger.download_cover("") is None

    def test_returns_bytes_on_success(self, stub_session, patch_session, fake_response):
        stub = stub_session({"cover.example.com": fake_response(200, content=b"IMG")})
        patch_session("music_sync.tagger.get_session", stub)
        assert tagger.download_cover("http://cover.example.com/a.jpg") == b"IMG"

    def test_http_error_returns_none(self, stub_session, patch_session, fake_response):
        stub = stub_session({"cover.example.com": fake_response(404, text="nope")})
        patch_session("music_sync.tagger.get_session", stub)
        assert tagger.download_cover("http://cover.example.com/a.jpg") is None

    def test_exception_returns_none(self, patch_session):
        class Boom:
            def get(self, *a, **k):
                raise RuntimeError("down")

        patch_session("music_sync.tagger.get_session", Boom())
        assert tagger.download_cover("http://cover.example.com/a.jpg") is None


class TestApplyTagsAndVerify:
    def test_missing_file(self, tmp_path):
        ok, msg = tagger.apply_tags_and_verify(str(tmp_path / "nope.flac"), "t", "a", "al")
        assert ok is False
        assert msg == "文件不存在"

    def test_unknown_extension_is_skipped(self, tmp_path, monkeypatch):
        f = tmp_path / "song.ogg"
        f.write_bytes(b"x")
        monkeypatch.setattr(tagger, "download_cover", lambda url: None)
        ok, msg = tagger.apply_tags_and_verify(str(f), "t", "a", "al")
        assert ok is True
        assert "未知格式" in msg

    def test_flac_branch_is_used(self, tmp_path, monkeypatch):
        f = tmp_path / "song.flac"
        f.write_bytes(b"x")
        seen = {}

        def fake_write(path, title, artist, album, lyrics="", cover_bytes=None):
            seen["path"] = path
            seen["title"] = title
            return True

        class Parsed:
            pass

        monkeypatch.setattr(tagger, "write_flac_tags", fake_write)
        monkeypatch.setattr(tagger, "download_cover", lambda url: None)
        monkeypatch.setattr(tagger, "File", lambda p: Parsed())

        ok, msg = tagger.apply_tags_and_verify(str(f), "断桥残雪", "许嵩", "专辑")
        assert ok is True
        assert seen["path"] == str(f)
        assert seen["title"] == "断桥残雪"
        assert "回读" in msg

    def test_mp3_branch_is_used(self, tmp_path, monkeypatch):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"x")
        called = {"mp3": False}

        def fake_write(path, title, artist, album, lyrics="", cover_bytes=None):
            called["mp3"] = True
            return True

        class Parsed:
            pass

        monkeypatch.setattr(tagger, "write_mp3_tags", fake_write)
        monkeypatch.setattr(tagger, "download_cover", lambda url: None)
        monkeypatch.setattr(tagger, "File", lambda p: Parsed())
        ok, _ = tagger.apply_tags_and_verify(str(f), "t", "a", "al")
        assert ok is True
        assert called["mp3"] is True

    def test_m4a_also_uses_mp3_branch(self, tmp_path, monkeypatch):
        f = tmp_path / "song.m4a"
        f.write_bytes(b"x")
        called = {"mp3": False}

        def fake_write(path, title, artist, album, lyrics="", cover_bytes=None):
            called["mp3"] = True
            return True

        class Parsed:
            pass

        monkeypatch.setattr(tagger, "write_mp3_tags", fake_write)
        monkeypatch.setattr(tagger, "download_cover", lambda url: None)
        monkeypatch.setattr(tagger, "File", lambda p: Parsed())
        tagger.apply_tags_and_verify(str(f), "t", "a", "al")
        assert called["mp3"] is True

    def test_write_failure_reported(self, tmp_path, monkeypatch):
        f = tmp_path / "song.flac"
        f.write_bytes(b"x")
        monkeypatch.setattr(tagger, "write_flac_tags", lambda *a, **k: False)
        monkeypatch.setattr(tagger, "download_cover", lambda url: None)
        ok, msg = tagger.apply_tags_and_verify(str(f), "t", "a", "al")
        assert ok is False
        assert "写入标签失败" in msg

    def test_readback_failure_reported(self, tmp_path, monkeypatch):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"x")
        monkeypatch.setattr(tagger, "write_mp3_tags", lambda *a, **k: True)
        monkeypatch.setattr(tagger, "download_cover", lambda url: None)
        # 写入成功但回读解析不到音频
        monkeypatch.setattr(tagger, "File", lambda p: None)
        ok, msg = tagger.apply_tags_and_verify(str(f), "t", "a", "al")
        assert ok is False
        assert "回读" in msg

    def test_cover_url_is_downloaded_and_passed_through(self, tmp_path, monkeypatch):
        f = tmp_path / "song.flac"
        f.write_bytes(b"x")
        got = {}

        def fake_cover(url):
            got["url"] = url
            return b"IMGBYTES"

        def fake_write(path, title, artist, album, lyrics="", cover_bytes=None):
            got["cover"] = cover_bytes
            return True

        class Parsed:
            pass

        monkeypatch.setattr(tagger, "download_cover", fake_cover)
        monkeypatch.setattr(tagger, "write_flac_tags", fake_write)
        monkeypatch.setattr(tagger, "File", lambda p: Parsed())

        tagger.apply_tags_and_verify(str(f), "t", "a", "al", cover_url="http://c/x.jpg")
        assert got["url"] == "http://c/x.jpg"
        assert got["cover"] == b"IMGBYTES"

    def test_empty_cover_url_skips_download(self, tmp_path, monkeypatch):
        f = tmp_path / "song.flac"
        f.write_bytes(b"x")
        monkeypatch.setattr(tagger, "download_cover", lambda url: pytest.fail("不应下载封面"))
        monkeypatch.setattr(tagger, "write_flac_tags", lambda *a, **k: True)

        class Parsed:
            pass

        monkeypatch.setattr(tagger, "File", lambda p: Parsed())
        ok, _ = tagger.apply_tags_and_verify(str(f), "t", "a", "al", cover_url="")
        assert ok is True
