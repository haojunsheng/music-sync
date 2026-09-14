"""配置层测试：默认值生成、读写往返、旧键名迁移、异常回退。

注意：本测试依赖 conftest 的 autouse fixture 把配置路径重定向到 tmp_path，
绝不会触碰 ~/.config/music-sync/config.json。
"""
import json

from music_sync import config as config_mod


class TestDefaults:
    def test_load_creates_default_file_when_absent(self):
        assert not config_mod.DEFAULT_CONFIG_FILE.exists()
        cfg = config_mod.load_config()
        # 首次加载会落盘一份默认配置
        assert config_mod.DEFAULT_CONFIG_FILE.exists()
        assert cfg.tolerance_seconds == 10
        assert cfg.quality_priority == ["flac"]
        assert cfg.allow_lossy_fallback is False
        assert cfg.download_dir.endswith("music-sync")

    def test_default_sources_order_is_preserved(self):
        cfg = config_mod.load_config()
        assert cfg.sources == [
            "qq", "migu", "kuwo", "netease", "kugou", "bilibili", "youtube", "1music"
        ]

    def test_default_blacklist_contains_common_noise(self):
        cfg = config_mod.load_config()
        lowered = [k.lower() for k in cfg.blacklist_keywords]
        for kw in ("dj", "live", "remix", "伴奏"):
            assert kw in lowered


class TestRoundTrip:
    def test_save_then_load_keeps_values(self):
        cfg = config_mod.load_config()
        cfg.tolerance_seconds = 30
        cfg.qq_cookie = "uin=123456; qm_keyst=abcdef"
        cfg.use_system_proxy = True
        config_mod.save_config(cfg)

        reloaded = config_mod.load_config()
        assert reloaded.tolerance_seconds == 30
        assert reloaded.qq_cookie == "uin=123456; qm_keyst=abcdef"
        assert reloaded.use_system_proxy is True

    def test_unicode_is_persisted_readable(self):
        cfg = config_mod.load_config()
        cfg.bilibili_cookie = "中文=值"
        config_mod.save_config(cfg)
        raw = config_mod.DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")
        # ensure_ascii=False，中文应原样落盘
        assert "中文" in raw


class TestOneMusicTokenKeyMigration:
    def test_saved_under_legacy_key_name(self):
        cfg = config_mod.load_config()
        cfg.token_1music = "TK-SECRET"
        config_mod.save_config(cfg)

        raw = json.loads(config_mod.DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
        assert raw["1music_token"] == "TK-SECRET"
        assert "token_1music" not in raw

    def test_loaded_from_legacy_key_name(self):
        config_mod.DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_mod.DEFAULT_CONFIG_FILE.write_text(
            json.dumps({"1music_token": "OLD-KEY"}), encoding="utf-8"
        )
        cfg = config_mod.load_config()
        assert cfg.token_1music == "OLD-KEY"


class TestRobustness:
    def test_unknown_fields_are_dropped(self):
        config_mod.DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_mod.DEFAULT_CONFIG_FILE.write_text(
            json.dumps({"tolerance_seconds": 5, "totally_unknown_field": 1}),
            encoding="utf-8",
        )
        cfg = config_mod.load_config()
        assert cfg.tolerance_seconds == 5
        assert not hasattr(cfg, "totally_unknown_field")

    def test_corrupted_json_falls_back_to_defaults(self):
        config_mod.DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_mod.DEFAULT_CONFIG_FILE.write_text("{ this is not json", encoding="utf-8")
        cfg = config_mod.load_config()
        # 解析失败时回退到内置默认值，而不是崩溃
        assert cfg.quality_priority == ["flac"]
        assert cfg.tolerance_seconds == 10

    def test_partial_config_uses_defaults_for_missing_fields(self):
        config_mod.DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_mod.DEFAULT_CONFIG_FILE.write_text(
            json.dumps({"tolerance_seconds": 7}), encoding="utf-8"
        )
        cfg = config_mod.load_config()
        assert cfg.tolerance_seconds == 7
        # 未提供的字段回落到 dataclass 默认值
        assert cfg.sources[0] == "qq"
        assert cfg.blacklist_keywords
