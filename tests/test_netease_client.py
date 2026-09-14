"""网易云客户端测试：Cookie 装载、登录态判断、云盘查重与上传前置校验。"""
import json

import pytest

from music_sync import config as config_mod
from music_sync import netease as ne_mod
from music_sync.netease import NetEaseClient

CLOUD_URL_KEY = "music.163.com/api/v1/cloud/get"


def _client(monkeypatch, stub):
    """构造客户端：先打桩 get_session，再实例化（__init__ 会立即取 session）。"""
    monkeypatch.setattr(ne_mod, "get_session", lambda *a, **k: stub)
    return NetEaseClient()


def _login_config():
    cfg = config_mod.load_config()
    cfg.netease_cookie = "MUSIC_U=token123; __csrf=csrf123"
    config_mod.save_config(cfg)


class TestCookieLoading:
    def test_parses_cookies_from_config(self, monkeypatch, stub_session):
        _login_config()
        client = _client(monkeypatch, stub_session({}))
        assert client.cookies["MUSIC_U"] == "token123"
        assert client.cookies["__csrf"] == "csrf123"

    def test_no_cookie_yields_empty_dict(self, monkeypatch, stub_session):
        client = _client(monkeypatch, stub_session({}))
        assert client.cookies == {}

    def test_cookie_file_is_read_when_present(self, monkeypatch, stub_session):
        # autouse fixture 已把 cookie 文件路径重定向到临时目录
        ne_mod.DEFAULT_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ne_mod.DEFAULT_COOKIE_FILE.write_text(
            json.dumps({"MUSIC_U": "from-file"}), encoding="utf-8"
        )
        client = _client(monkeypatch, stub_session({}))
        assert client.cookies["MUSIC_U"] == "from-file"


class TestLoginState:
    def test_false_without_music_u(self, monkeypatch, stub_session):
        client = _client(monkeypatch, stub_session({}))
        assert client.is_logged_in() is False

    def test_true_when_cloud_api_returns_code_200(self, monkeypatch, stub_session, fake_response):
        _login_config()
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []})})
        client = _client(monkeypatch, stub)
        assert client.is_logged_in() is True

    def test_false_when_cloud_api_returns_empty_body(self, monkeypatch, stub_session, fake_response):
        _login_config()
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, text="")})
        client = _client(monkeypatch, stub)
        # Cookie 存在但服务端无效，仍应视为未登录
        assert client.is_logged_in() is False

    def test_false_when_cookie_expired(self, monkeypatch, stub_session, fake_response):
        _login_config()
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data={"code": 301, "msg": "need login"})})
        client = _client(monkeypatch, stub)
        assert client.is_logged_in() is False


class TestCloudSongExists:
    def test_false_when_not_logged_in(self, monkeypatch, stub_session):
        client = _client(monkeypatch, stub_session({}))
        assert client.check_cloud_song_exists("断桥残雪", "许嵩") is False

    def test_detects_existing_private_cloud_song(self, monkeypatch, stub_session, fake_response):
        _login_config()
        payload = {
            "code": 200,
            "data": [{"privateCloud": {"songName": "断桥残雪", "artist": "许嵩"}}],
        }
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data=payload)})
        client = _client(monkeypatch, stub)
        assert client.check_cloud_song_exists("断桥残雪", "许嵩") is True

    def test_returns_false_when_absent(self, monkeypatch, stub_session, fake_response):
        _login_config()
        payload = {"code": 200, "data": [{"privateCloud": {"songName": "幻听", "artist": "许嵩"}}]}
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data=payload)})
        client = _client(monkeypatch, stub)
        assert client.check_cloud_song_exists("断桥残雪", "许嵩") is False

    def test_supports_flat_song_fields(self, monkeypatch, stub_session, fake_response):
        # 旧版接口直接平铺 song/artist 字段
        _login_config()
        payload = {"code": 200, "data": [{"songName": "断桥残雪", "artist": "许嵩"}]}
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data=payload)})
        client = _client(monkeypatch, stub)
        assert client.check_cloud_song_exists("断桥残雪", "许嵩") is True


class TestWeapiRequest:
    def test_returns_dict_on_success(self, monkeypatch, stub_session, fake_response):
        stub = stub_session({"music.163.com/weapi": fake_response(200, json_data={"code": 200})})
        client = _client(monkeypatch, stub)
        assert client.weapi_request("https://music.163.com/weapi/x", {"a": 1}) == {"code": 200}

    def test_empty_body_returns_empty_dict(self, monkeypatch, stub_session, fake_response):
        stub = stub_session({"music.163.com/weapi": fake_response(200, text="")})
        client = _client(monkeypatch, stub)
        assert client.weapi_request("https://music.163.com/weapi/x", {"a": 1}) == {}

    def test_exception_returns_empty_dict(self, monkeypatch, stub_session):
        class Boom:
            def post(self, *a, **k):
                raise RuntimeError("down")

            def get(self, *a, **k):
                raise RuntimeError("down")

        client = _client(monkeypatch, Boom())
        assert client.weapi_request("https://music.163.com/weapi/x", {"a": 1}) == {}


class TestUploadToCloud:
    def test_requires_login(self, monkeypatch, stub_session, tmp_path, capsys):
        client = _client(monkeypatch, stub_session({}))
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        assert client.upload_to_cloud(str(f), "断桥残雪", "许嵩", "专辑") is False
        assert "未登录" in capsys.readouterr().out

    def test_missing_file_is_reported(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []})})
        client = _client(monkeypatch, stub)
        assert client.upload_to_cloud(str(tmp_path / "nope.mp3"), "t", "a", "al") is False
        assert "文件不存在" in capsys.readouterr().out

    def test_ape_is_skipped(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = stub_session({CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []})})
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.ape"
        f.write_bytes(b"x")
        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "APE" in capsys.readouterr().out


class TestQrLogin:
    def test_returns_false_when_unikey_unavailable(self, monkeypatch, stub_session, fake_response):
        stub = stub_session(
            {
                "music.163.com/api/login/qrcode/unikey": fake_response(200, json_data={"code": 500}),
                "weapi/login/qrcode/unikey?csrf_token=": fake_response(200, json_data={}),
            }
        )
        client = _client(monkeypatch, stub)
        assert client.get_login_qr_key() is None
        assert client.login_with_qrcode(timeout_sec=0) is False
