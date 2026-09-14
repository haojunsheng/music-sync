"""YouTube 音源测试。

该源不走 HTTP 会话，而是调用 yt-dlp 子进程，因此这里打桩的是
shutil.which 与 subprocess.run。
"""
import json
import subprocess

import pytest

from music_sync.sources.youtube import YouTubeSource


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _dump_line(**kwargs):
    payload = {
        "id": "vid123",
        "title": "许嵩 断桥残雪",
        "uploader": "Some Channel",
        "duration": 227,
        "webpage_url": "https://www.youtube.com/watch?v=vid123",
    }
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False) + "\n"


@pytest.fixture
def ytdlp_present(monkeypatch):
    monkeypatch.setattr("music_sync.sources.youtube.shutil.which", lambda name: "/usr/local/bin/yt-dlp")


@pytest.fixture
def ytdlp_absent(monkeypatch):
    monkeypatch.setattr("music_sync.sources.youtube.shutil.which", lambda name: None)


class TestYouTubeSource:
    def test_missing_ytdlp_returns_empty(self, ytdlp_absent):
        assert YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_parses_dump_json_lines(self, ytdlp_present, monkeypatch):
        monkeypatch.setattr(
            "music_sync.sources.youtube.subprocess.run",
            lambda cmd, **kw: FakeCompleted(0, _dump_line()),
        )
        out = YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
        cand = out[0]
        assert cand.source == "youtube"
        assert cand.song_id == "vid123"
        assert cand.title == "许嵩 断桥残雪"
        assert cand.artist == "Some Channel"
        assert cand.duration_seconds == 227
        assert cand.download_url == "https://www.youtube.com/watch?v=vid123"

    def test_multiple_lines_all_parsed(self, ytdlp_present, monkeypatch):
        stdout = _dump_line(id="a") + _dump_line(id="b")
        monkeypatch.setattr(
            "music_sync.sources.youtube.subprocess.run", lambda cmd, **kw: FakeCompleted(0, stdout)
        )
        out = YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert {c.song_id for c in out} == {"a", "b"}

    def test_nonzero_returncode_returns_empty(self, ytdlp_present, monkeypatch):
        monkeypatch.setattr(
            "music_sync.sources.youtube.subprocess.run",
            lambda cmd, **kw: FakeCompleted(1, stdout="", stderr="ERROR: network unreachable"),
        )
        assert YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_timeout_returns_empty(self, ytdlp_present, monkeypatch):
        def raise_timeout(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 30)

        monkeypatch.setattr("music_sync.sources.youtube.subprocess.run", raise_timeout)
        assert YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_empty_stdout_returns_empty(self, ytdlp_present, monkeypatch):
        monkeypatch.setattr(
            "music_sync.sources.youtube.subprocess.run", lambda cmd, **kw: FakeCompleted(0, stdout="")
        )
        assert YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_blacklisted_title_filtered(self, ytdlp_present, monkeypatch):
        monkeypatch.setattr(
            "music_sync.sources.youtube.subprocess.run",
            lambda cmd, **kw: FakeCompleted(0, _dump_line(title="断桥残雪 (Live cover)")),
        )
        assert YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227) == []

    def test_malformed_json_line_skipped(self, ytdlp_present, monkeypatch):
        stdout = "{not json}\n" + _dump_line()
        monkeypatch.setattr(
            "music_sync.sources.youtube.subprocess.run", lambda cmd, **kw: FakeCompleted(0, stdout)
        )
        out = YouTubeSource().search_and_resolve("断桥残雪", "许嵩", 227)
        assert len(out) == 1
