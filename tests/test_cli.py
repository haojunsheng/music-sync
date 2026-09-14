"""CLI 测试：config 子命令的参数解析与落盘、sync 参数透传。

回归点：config 子命令曾访问未定义的 args.netease_cookie，导致
`music-sync config` 直接 AttributeError 崩溃。
"""
import sys

import pytest

from music_sync import cli
from music_sync import config as config_mod
from music_sync import pipeline


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["music-sync"] + argv)
    cli.main()


class TestConfigCommand:
    def test_config_runs_without_arguments(self, monkeypatch, capsys):
        """回归：不带参数运行 config 不应崩溃。"""
        _run(monkeypatch, ["config"])
        out = capsys.readouterr().out
        assert "quality_priority" in out
        assert "allow_lossy_fallback" in out

    def test_shows_default_quality_policy(self, monkeypatch, capsys):
        _run(monkeypatch, ["config"])
        out = capsys.readouterr().out
        assert "flac" in out and "320k" in out

    def test_sets_quality_priority(self, monkeypatch):
        _run(monkeypatch, ["config", "--quality-priority", "flac,320k"])
        assert config_mod.load_config().quality_priority == ["flac", "320k"]

    def test_quality_priority_is_lowercased_and_trimmed(self, monkeypatch):
        _run(monkeypatch, ["config", "--quality-priority", " FLAC , 320K , "])
        assert config_mod.load_config().quality_priority == ["flac", "320k"]

    def test_sets_allow_lossy_false(self, monkeypatch):
        _run(monkeypatch, ["config", "--allow-lossy", "false"])
        assert config_mod.load_config().allow_lossy_fallback is False

    def test_sets_allow_lossy_true(self, monkeypatch):
        _run(monkeypatch, ["config", "--allow-lossy", "true"])
        assert config_mod.load_config().allow_lossy_fallback is True

    def test_sets_tolerance(self, monkeypatch):
        _run(monkeypatch, ["config", "--tolerance-seconds", "20"])
        assert config_mod.load_config().tolerance_seconds == 20

    def test_sets_netease_cookie(self, monkeypatch):
        _run(monkeypatch, ["config", "--netease-cookie", "MUSIC_U=abc"])
        assert config_mod.load_config().netease_cookie == "MUSIC_U=abc"

    def test_sets_qq_cookie(self, monkeypatch):
        _run(monkeypatch, ["config", "--qq-cookie", "uin=123"])
        assert config_mod.load_config().qq_cookie == "uin=123"

    def test_no_change_when_no_flags(self, monkeypatch, tmp_path):
        # 不带任何修改参数时不应写盘（文件内容保持不变）
        _run(monkeypatch, ["config"])
        before = config_mod.DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")
        _run(monkeypatch, ["config"])
        after = config_mod.DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")
        assert before == after


class TestSyncCommand:
    def test_sync_passes_arguments_and_respects_quality_policy(self, monkeypatch, capsys):
        captured = {}

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            captured.update(
                title=title, artist=artist, album=album, dry_run=dry_run,
                no_upload=no_upload, flac_only=flac_only,
            )
            return True

        monkeypatch.setattr(cli, "sync_single_track", fake_sync)
        _run(monkeypatch, ["sync", "断桥残雪", "--artist", "许嵩", "--dry-run"])
        assert captured == {
            "title": "断桥残雪",
            "artist": "许嵩",
            "album": "",
            "dry_run": True,
            "no_upload": False,
            "flac_only": False,
        }

    def test_flac_only_flag_is_forwarded(self, monkeypatch):
        captured = {}

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            captured["flac_only"] = flac_only
            return True

        monkeypatch.setattr(cli, "sync_single_track", fake_sync)
        _run(monkeypatch, ["sync", "断桥残雪", "--flac-only"])
        assert captured["flac_only"] is True

    def test_no_upload_flag_is_forwarded(self, monkeypatch):
        captured = {}

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            captured["no_upload"] = no_upload
            return True

        monkeypatch.setattr(cli, "sync_single_track", fake_sync)
        _run(monkeypatch, ["sync", "断桥残雪", "--no-upload"])
        assert captured["no_upload"] is True


class TestBatchCommand:
    def test_batch_forwards_csv_path(self, monkeypatch, tmp_path):
        captured = {}

        def fake_batch(csv_path, dry_run=False, no_upload=False):
            captured.update(csv_path=csv_path, dry_run=dry_run)

        monkeypatch.setattr(cli, "sync_batch_csv", fake_batch)
        _run(monkeypatch, ["batch", "songs.csv", "--dry-run"])
        assert captured["csv_path"] == "songs.csv"
        assert captured["dry_run"] is True


class TestArtistCommand:
    def test_forwards_name_and_limit(self, monkeypatch):
        captured = {}

        def fake_artist(artist, limit=50, dry_run=False, no_upload=False):
            captured.update(artist=artist, limit=limit, dry_run=dry_run, no_upload=no_upload)

        monkeypatch.setattr(cli, "sync_artist", fake_artist)
        _run(monkeypatch, ["artist", "许嵩", "--limit", "30"])
        assert captured == {"artist": "许嵩", "limit": 30, "dry_run": False, "no_upload": False}

    def test_default_limit_is_50(self, monkeypatch):
        captured = {}

        def fake_artist(artist, limit=50, dry_run=False, no_upload=False):
            captured["limit"] = limit

        monkeypatch.setattr(cli, "sync_artist", fake_artist)
        _run(monkeypatch, ["artist", "许嵩"])
        assert captured["limit"] == 50

    def test_flags_are_forwarded(self, monkeypatch):
        captured = {}

        def fake_artist(artist, limit=50, dry_run=False, no_upload=False):
            captured.update(dry_run=dry_run, no_upload=no_upload)

        monkeypatch.setattr(cli, "sync_artist", fake_artist)
        _run(monkeypatch, ["artist", "许嵩", "--dry-run", "--no-upload"])
        assert captured == {"dry_run": True, "no_upload": True}

    def test_artist_requires_a_name(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["music-sync", "artist"])
        with pytest.raises(SystemExit):
            cli.main()
