"""流水线测试：音源遍历、FLAC 策略、候选排序、dry-run、下载与批量同步。

最重要的回归：`allow_lossy_fallback` 开关必须真正生效。
旧实现 `only_flac = flac_only or not allow_lossy_fallback or quality_priority == ["flac"]`
中第三项恒真（默认 quality_priority 就是 ["flac"]），导致该开关完全失效。
"""
import json

import pytest

from music_sync import config as config_mod
from music_sync import pipeline
from music_sync.metadata import OfficialMetadata
from music_sync.sources.base import TrackCandidate


def _meta(duration=227):
    return OfficialMetadata("断桥残雪", "许嵩", "许嵩早期单曲集", duration, source="MusicBrainz")


def _cand(quality="flac", ext="flac", source="qq", url=None):
    return TrackCandidate(
        source=source,
        song_id="ID1",
        title="断桥残雪",
        artist="许嵩",
        album="",
        duration_seconds=227,
        quality=quality,
        file_ext=ext,
        download_url=url or f"http://cdn/a.{ext}",
    )


class FakeSource:
    """可编程的音源桩。"""

    def __init__(self, candidates=None, error=None):
        self.candidates = list(candidates or [])
        self.error = error
        self.searched = False
        self.name = "fake"

    def search_and_resolve(self, title, artist, target_duration=0):
        self.searched = True
        if self.error:
            raise self.error
        return list(self.candidates)


def _configure(monkeypatch, sources, *, allow_lossy=None, flac_only_priority=None, download_dir=None):
    cfg = config_mod.load_config()
    # allow_lossy 为 None 时沿用配置默认策略（默认允许 320k 兜底）
    if allow_lossy is not None:
        cfg.allow_lossy_fallback = allow_lossy
    cfg.sources = list(sources.keys())
    if flac_only_priority is not None:
        cfg.quality_priority = flac_only_priority
    if download_dir is not None:
        cfg.download_dir = str(download_dir)
    config_mod.save_config(cfg)

    monkeypatch.setattr(pipeline, "SOURCE_REGISTRY", {k: object for k in sources})
    monkeypatch.setattr(pipeline, "get_source", lambda name: sources[name])
    monkeypatch.setattr(pipeline, "get_official_metadata", lambda t, a: _meta())


class TestFlacPolicy:
    def test_lossy_candidate_skipped_when_fallback_disabled(self, monkeypatch, capsys):
        src = FakeSource([_cand("320k", "mp3")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=False)

        ok = pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert ok is False
        out = capsys.readouterr().out
        assert "仅限 FLAC" in out

    def test_lossy_candidate_accepted_when_fallback_enabled(self, monkeypatch, capsys):
        """回归：allow_lossy_fallback=True 时必须接受 320k 兜底。"""
        src = FakeSource([_cand("320k", "mp3")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)

        ok = pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert ok is True
        assert "最终选用" in capsys.readouterr().out

    def test_flac_candidate_accepted_by_default(self, monkeypatch):
        src = FakeSource([_cand("flac", "flac")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=False)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is True


class TestQualityPolicy:
    """匹配策略：优先无损；无无损时接受 320k；低于 320k 一律拒绝。

    且找到无损即停止，不需要把每个音源都试一遍。
    """

    def test_128k_is_rejected(self, monkeypatch, capsys):
        src = FakeSource([_cand("128k", "mp3")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is False
        assert "低于可接受档位" in capsys.readouterr().out

    def test_192k_is_rejected(self, monkeypatch):
        # B 站 / YouTube 常见 192k，同样属于"更低音质"
        src = FakeSource([_cand("192k", "m4a")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is False

    def test_96k_is_rejected(self, monkeypatch):
        src = FakeSource([_cand("96k", "mp3")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is False

    def test_320k_accepted_when_no_lossless(self, monkeypatch, capsys):
        src = FakeSource([_cand("320k", "mp3")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is True
        assert "320K" in capsys.readouterr().out.upper()

    def test_lossless_stops_iteration_immediately(self, monkeypatch):
        """找到无损即停止，不再检索后续音源。"""
        first = FakeSource([_cand("flac", "flac", source="qq")])
        second = FakeSource([_cand("flac", "flac", source="kugou")])
        _configure(monkeypatch, {"qq": first, "kugou": second})
        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert first.searched is True
        assert second.searched is False

    def test_keeps_searching_for_lossless_after_lossy_hit(self, monkeypatch):
        """先在某个源拿到 320k，仍要继续找无损，不能就此停手。"""
        lossy = FakeSource([_cand("320k", "mp3", source="qq")])
        lossless = FakeSource([_cand("flac", "flac", source="kugou")])
        _configure(monkeypatch, {"qq": lossy, "kugou": lossless})
        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert lossy.searched is True
        assert lossless.searched is True

    def test_prefers_lossless_over_lossy_across_sources(self, monkeypatch, capsys):
        lossy = FakeSource([_cand("320k", "mp3", source="qq", url="http://cdn/lossy.mp3")])
        lossless = FakeSource([_cand("flac", "flac", source="kugou", url="http://cdn/lossless.flac")])
        _configure(monkeypatch, {"qq": lossy, "kugou": lossless})
        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        # 最终应选中后到的无损，而不是先遇到的 320k
        assert "http://cdn/lossless.flac" in capsys.readouterr().out

    def test_lossy_fallback_kept_when_no_lossless_anywhere(self, monkeypatch, capsys):
        a = FakeSource([_cand("320k", "mp3", source="qq", url="http://cdn/a.mp3")])
        b = FakeSource([_cand("128k", "mp3", source="kugou", url="http://cdn/b.mp3")])
        _configure(monkeypatch, {"qq": a, "kugou": b})
        ok = pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert ok is True
        # 320k 兜底被保留，128k 被丢弃
        assert "http://cdn/a.mp3" in capsys.readouterr().out

    def test_higher_quality_preferred_within_one_source(self, monkeypatch, capsys):
        src = FakeSource(
            [
                _cand("320k", "mp3", url="http://cdn/low.mp3"),
                _cand("flac", "flac", url="http://cdn/high.flac"),
            ]
        )
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)
        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert "http://cdn/high.flac" in capsys.readouterr().out

    def test_ape_counts_as_lossless(self, monkeypatch):
        src = FakeSource([_cand("ape", "ape", source="qq")])
        other = FakeSource([_cand("320k", "mp3", source="kugou")])
        _configure(monkeypatch, {"qq": src, "kugou": other})
        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        # ape 属于无损，命中后应停止检索
        assert other.searched is False

    def test_all_candidates_below_floor_returns_false(self, monkeypatch):
        a = FakeSource([_cand("128k", "mp3", source="qq")])
        b = FakeSource([_cand("96k", "mp3", source="kugou")])
        _configure(monkeypatch, {"qq": a, "kugou": b})
        # 两个源都只有低于 320k 的资源 -> 整体失败
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is False


class TestCandidateSelection:
    def test_flac_preferred_over_mp3_in_same_source(self, monkeypatch, capsys):
        src = FakeSource([_cand("320k", "mp3"), _cand("flac", "flac")])
        _configure(monkeypatch, {"qq": src}, allow_lossy=True)

        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        out = capsys.readouterr().out
        # quality_priority 默认 ["flac"]，flac 排序在前
        assert "FLAC" in out.upper()

    def test_first_hitting_source_wins(self, monkeypatch):
        first = FakeSource([_cand("flac", "flac", source="qq")])
        second = FakeSource([_cand("flac", "flac", source="kugou")])
        _configure(monkeypatch, {"qq": first, "kugou": second})

        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        assert first.searched is True
        # 已命中后不应继续检索后续音源
        assert second.searched is False

    def test_empty_source_falls_through_to_next(self, monkeypatch):
        empty = FakeSource([])
        good = FakeSource([_cand("flac", "flac", source="kugou")])
        _configure(monkeypatch, {"qq": empty, "kugou": good})

        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is True
        assert empty.searched and good.searched

    def test_source_exception_does_not_abort_iteration(self, monkeypatch):
        broken = FakeSource(error=RuntimeError("boom"))
        good = FakeSource([_cand("flac", "flac", source="kugou")])
        _configure(monkeypatch, {"qq": broken, "kugou": good})

        # 单个音源抛异常应被吞掉并继续下一个音源
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is True

    def test_all_sources_empty_returns_false(self, monkeypatch):
        _configure(monkeypatch, {"qq": FakeSource([]), "kugou": FakeSource([])})
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is False

    def test_unregistered_source_is_skipped(self, monkeypatch):
        allowed = FakeSource([_cand("flac", "flac")])
        _configure(monkeypatch, {"qq": allowed})
        # 配置里出现未注册的音源名时不应报错
        cfg = config_mod.load_config()
        cfg.sources = ["not_a_source", "qq"]
        config_mod.save_config(cfg)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is True


class TestDryRun:
    def test_dry_run_does_not_download(self, monkeypatch):
        src = FakeSource([_cand("flac", "flac")])
        _configure(monkeypatch, {"qq": src})

        called = {"download": False}

        def fake_download(*args, **kwargs):
            called["download"] = True
            return True

        monkeypatch.setattr(pipeline, "download_file", fake_download)
        assert pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True) is True
        assert called["download"] is False

    def test_dry_run_reports_candidate_info(self, monkeypatch, capsys):
        src = FakeSource([_cand("flac", "flac", url="http://cdn/x.flac")])
        _configure(monkeypatch, {"qq": src})
        pipeline.sync_single_track("断桥残雪", "许嵩", dry_run=True)
        out = capsys.readouterr().out
        assert "Dry-Run" in out
        assert "http://cdn/x.flac" in out


class TestDownloadFile:
    def test_success_writes_file(self, stub_session, patch_session, fake_response, tmp_path):
        stub = stub_session({"cdn.example.com": fake_response(200, content=b"FAKEDATA")})
        patch_session("music_sync.pipeline.get_session", stub)

        target = tmp_path / "out" / "song.flac"
        ok = pipeline.download_file("http://cdn.example.com/a.flac", str(target))
        assert ok is True
        assert target.read_bytes() == b"FAKEDATA"

    def test_http_error_returns_false(self, stub_session, patch_session, fake_response, tmp_path):
        stub = stub_session({"cdn.example.com": fake_response(404, text="nope")})
        patch_session("music_sync.pipeline.get_session", stub)
        assert pipeline.download_file("http://cdn.example.com/a.flac", str(tmp_path / "x.flac")) is False

    def test_exception_returns_false(self, stub_session, patch_session, tmp_path):
        class Boom:
            def get(self, *a, **k):
                raise RuntimeError("network down")

        patch_session("music_sync.pipeline.get_session", Boom())
        assert pipeline.download_file("http://cdn.example.com/a.flac", str(tmp_path / "x.flac")) is False


class TestBatchSync:
    def test_batch_reports_success_and_failure(self, monkeypatch, tmp_path, capsys):
        csv_file = tmp_path / "songs.csv"
        csv_file.write_text(
            "title,artist\n断桥残雪,许嵩\n幻听,许嵩\n", encoding="utf-8-sig"
        )

        results = {"断桥残雪": True, "幻听": False}

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            return results[title]

        monkeypatch.setattr(pipeline, "sync_single_track", fake_sync)
        pipeline.sync_batch_csv(str(csv_file), dry_run=True)

        out = capsys.readouterr().out
        assert "断桥残雪" in out and "幻听" in out
        assert "成功: 1" in out
        assert "失败: 1" in out

    def test_batch_handles_utf8_bom(self, monkeypatch, tmp_path):
        csv_file = tmp_path / "bom.csv"
        csv_file.write_text("title,artist\n断桥残雪,许嵩\n", encoding="utf-8-sig")

        seen = []

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            seen.append((title, artist))
            return True

        monkeypatch.setattr(pipeline, "sync_single_track", fake_sync)
        pipeline.sync_batch_csv(str(csv_file))
        # BOM 不应残留到 title 上
        assert seen == [("断桥残雪", "许嵩")]

    def test_batch_skips_rows_without_title(self, monkeypatch, tmp_path):
        csv_file = tmp_path / "x.csv"
        csv_file.write_text("title,artist\n,许嵩\n断桥残雪,许嵩\n", encoding="utf-8")

        seen = []

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            seen.append(title)
            return True

        monkeypatch.setattr(pipeline, "sync_single_track", fake_sync)
        pipeline.sync_batch_csv(str(csv_file))
        assert seen == ["断桥残雪"]

    def test_missing_csv_file(self, tmp_path, capsys):
        pipeline.sync_batch_csv(str(tmp_path / "nope.csv"))
        assert "不存在" in capsys.readouterr().out

    def test_batch_continues_after_exception(self, monkeypatch, tmp_path):
        csv_file = tmp_path / "x.csv"
        csv_file.write_text("title,artist\nA,甲\nB,乙\n", encoding="utf-8")

        def fake_sync(title, artist="", album="", dry_run=False, no_upload=False, flac_only=False):
            if title == "A":
                raise RuntimeError("boom")
            return True

        monkeypatch.setattr(pipeline, "sync_single_track", fake_sync)
        # 单条异常不应中断批量任务
        pipeline.sync_batch_csv(str(csv_file))
