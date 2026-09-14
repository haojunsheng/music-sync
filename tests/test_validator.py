"""校验层测试：歌手/歌名匹配、黑名单、时长与音频文件校验。

这一层是全流程的"守门员"：错判会直接导致命中翻唱或丢弃正确文件，
所以边界条件（空值、容差临界、分隔符）都要覆盖。
"""
import pytest

from music_sync import validator


class TestArtistMatch:
    def test_exact_match(self):
        assert validator.is_artist_match("许嵩", "许嵩")

    def test_empty_target_always_matches(self):
        # 未指定目标歌手时不做限制
        assert validator.is_artist_match("任何人", "")

    def test_case_insensitive(self):
        assert validator.is_artist_match("Jay Chou", "jay chou")

    def test_slash_separator(self):
        assert validator.is_artist_match("许嵩/Kent王健", "许嵩")

    def test_ampersand_separator(self):
        assert validator.is_artist_match("许嵩&Kent王健", "许嵩")

    def test_chinese_enumeration_separator(self):
        assert validator.is_artist_match("许嵩、Kent王健", "许嵩")

    def test_substring_both_directions(self):
        assert validator.is_artist_match("许嵩", "许嵩Vae")
        assert validator.is_artist_match("许嵩Vae", "许嵩")

    def test_space_insensitive(self):
        assert validator.is_artist_match("Jay Chou", "jaychou")

    def test_mismatch(self):
        assert not validator.is_artist_match("沐萧", "许嵩")


class TestTitleMatch:
    def test_exact_match(self):
        assert validator.is_title_match("断桥残雪", "断桥残雪")

    def test_empty_target_always_matches(self):
        assert validator.is_title_match("任意标题", "")

    def test_candidate_with_suffix_still_matches(self):
        assert validator.is_title_match("断桥残雪 (Live)", "断桥残雪")

    def test_target_with_suffix_still_matches(self):
        assert validator.is_title_match("断桥残雪", "断桥残雪 (Live)")

    def test_space_insensitive(self):
        assert validator.is_title_match("断桥 残雪", "断桥残雪")

    def test_mismatch(self):
        assert not validator.is_title_match("幻听", "断桥残雪")


class TestValidateCandidateMatch:
    def test_both_match(self):
        assert validator.validate_candidate_match("断桥残雪", "许嵩", "断桥残雪", "许嵩")

    def test_title_mismatch_rejected(self):
        assert not validator.validate_candidate_match("幻听", "许嵩", "断桥残雪", "许嵩")

    def test_artist_mismatch_rejected(self):
        assert not validator.validate_candidate_match("断桥残雪", "沐萧", "断桥残雪", "许嵩")

    def test_empty_target_artist_only_checks_title(self):
        assert validator.validate_candidate_match("断桥残雪", "任意歌手", "断桥残雪", "")

    def test_regression_cover_version_is_rejected(self):
        """回归：QQ 曾把免费的《断桥残雪 (柔情版) - 沐萧》当作许嵩原唱返回。

        歌名是子串匹配所以会通过 title 校验，必须靠歌手校验拦下。
        """
        assert not validator.validate_candidate_match(
            "断桥残雪 (柔情版)", "沐萧", "断桥残雪", "许嵩"
        )


class TestBlacklist:
    def test_default_keyword_hit_dj(self):
        hit, kw = validator.check_blacklist("断桥残雪 (DJ版)")
        assert hit is True and kw.lower() == "dj"

    def test_default_keyword_hit_live(self):
        hit, _ = validator.check_blacklist("断桥残雪 (Live)")
        assert hit is True

    def test_default_keyword_hit_cover(self):
        hit, _ = validator.check_blacklist("断桥残雪（Cover 南妮）")
        assert hit is True

    def test_clean_title_not_blacklisted(self):
        hit, kw = validator.check_blacklist("断桥残雪 许嵩早期单曲集")
        assert hit is False and kw == ""

    def test_empty_text(self):
        assert validator.check_blacklist("") == (False, "")
        assert validator.check_blacklist(None) == (False, "")

    def test_custom_keywords_override_default(self):
        hit, kw = validator.check_blacklist("我的自定义词", custom_keywords=["自定义"])
        assert hit is True and kw == "自定义"

    def test_custom_keywords_do_not_fall_back_to_default(self):
        # 传入自定义列表后，默认的 dj 规则不再生效
        hit, _ = validator.check_blacklist("断桥残雪 (DJ版)", custom_keywords=["另一个词"])
        assert hit is False

    def test_case_insensitive(self):
        hit, _ = validator.check_blacklist("MY REMIX VERSION")
        assert hit is True


class TestValidateDuration:
    def test_zero_target_skips_check(self):
        assert validator.validate_duration(999, 0) is True

    def test_zero_candidate_skips_check(self):
        assert validator.validate_duration(0, 227) is True

    def test_within_tolerance(self):
        assert validator.validate_duration(230, 227, tolerance=10) is True

    def test_exactly_on_tolerance_boundary(self):
        assert validator.validate_duration(237, 227, tolerance=10) is True

    def test_outside_tolerance(self):
        assert validator.validate_duration(238, 227, tolerance=10) is False

    def test_negative_direction_outside_tolerance(self):
        assert validator.validate_duration(216, 227, tolerance=10) is False

    def test_custom_tolerance(self):
        assert validator.validate_duration(200, 227, tolerance=30) is True


class TestValidateAudioFile:
    def test_missing_file(self, tmp_path):
        ok, dur, msg = validator.validate_audio_file(str(tmp_path / "nope.flac"), 227)
        assert ok is False and dur == 0.0 and msg == "文件不存在"

    def test_unparsable_file(self, monkeypatch, tmp_path):
        f = tmp_path / "a.flac"
        f.write_bytes(b"\x00")
        monkeypatch.setattr(validator, "File", lambda p: None)
        ok, dur, msg = validator.validate_audio_file(str(f), 227)
        assert ok is False and "无法解析" in msg

    def test_duration_within_tolerance(self, monkeypatch, tmp_path):
        f = tmp_path / "a.flac"
        f.write_bytes(b"\x00")

        class Info:
            length = 227.0

        class Audio:
            info = Info()

        monkeypatch.setattr(validator, "File", lambda p: Audio())
        ok, dur, msg = validator.validate_audio_file(str(f), 227, tolerance=10)
        assert ok is True
        assert abs(dur - 227.0) < 0.01
        assert msg == "OK"

    def test_duration_outside_tolerance(self, monkeypatch, tmp_path):
        f = tmp_path / "a.flac"
        f.write_bytes(b"\x00")

        class Info:
            length = 300.0

        class Audio:
            info = Info()

        monkeypatch.setattr(validator, "File", lambda p: Audio())
        ok, dur, msg = validator.validate_audio_file(str(f), 227, tolerance=10)
        assert ok is False
        assert "超出容差" in msg

    def test_zero_target_skips_duration_check(self, monkeypatch, tmp_path):
        f = tmp_path / "a.flac"
        f.write_bytes(b"\x00")

        class Info:
            length = 5.0

        class Audio:
            info = Info()

        monkeypatch.setattr(validator, "File", lambda p: Audio())
        ok, dur, _ = validator.validate_audio_file(str(f), 0)
        assert ok is True
