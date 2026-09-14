"""网易云客户端测试：Cookie 装载、登录态判断、云盘查重与上传前置校验。"""
import hashlib
import json

import pytest
from Crypto.Cipher import AES

from music_sync import config as config_mod
from music_sync import netease as ne_mod
from music_sync.netease import NetEaseClient
from music_sync.netease_crypto import EAPI_KEY, EAPI_SEP

CLOUD_URL_KEY = "music.163.com/api/v1/cloud/get"
CHECK_KEY = "api/cloud/upload/check"
TOKEN_KEY = "api/nos/token/alloc"
INFO_KEY = "api/upload/cloud/info/v2"
PUB_KEY = "api/cloud/pub/v2"
LBS_KEY = "wanproxy.127.net/lbs"
NOS_HOST_KEY = "upload.example.com"


def _decode_eapi_payload(params_hex: str):
    """解密 eapi 的 params，还原 [路径, 明文 JSON, 校验摘要]，用于断言线上参数。"""
    raw = AES.new(EAPI_KEY.encode("utf-8"), AES.MODE_ECB).decrypt(bytes.fromhex(params_hex))
    raw = raw[: -raw[-1]]
    return raw.decode("utf-8").split(EAPI_SEP)


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


class TestEapiRequest:
    """eapi 是现行通道；weapi 已被服务端下线（返回 200 + 空 body）。"""

    def test_returns_parsed_json(self, monkeypatch, stub_session, fake_response):
        stub = stub_session({"interface.music.163.com": fake_response(200, json_data={"code": 200})})
        client = _client(monkeypatch, stub)
        assert client.eapi_request("/api/nos/token/alloc", {"a": 1}) == {"code": 200}

    def test_empty_body_returns_empty_dict(self, monkeypatch, stub_session, fake_response):
        stub = stub_session({"interface.music.163.com": fake_response(200, text="")})
        client = _client(monkeypatch, stub)
        assert client.eapi_request("/api/x", {"a": 1}) == {}

    def test_exception_returns_empty_dict(self, monkeypatch, stub_session):
        class Boom:
            def post(self, *a, **k):
                raise RuntimeError("down")

            def get(self, *a, **k):
                raise RuntimeError("down")

        client = _client(monkeypatch, Boom())
        assert client.eapi_request("/api/x", {"a": 1}) == {}

    def test_cookie_header_is_populated_from_config(self, monkeypatch, stub_session, fake_response):
        _login_config()
        stub = stub_session({"interface.music.163.com": fake_response(200, json_data={"code": 200})})
        client = _client(monkeypatch, stub)
        assert "MUSIC_U=token123" in client._cookie_header()


class TestUploadToCloudRobustness:
    def test_check_api_error_is_reported(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        """回归：check 接口报错时必须给出服务端原因，不能静默按 needUpload=True 往下走。"""
        _login_config()
        stub = stub_session(
            {
                CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []}),
                CHECK_KEY: fake_response(200, json_data={"code": 400, "message": "参数错误"}),
            }
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "参数错误" in capsys.readouterr().out

    def test_code_only_error_does_not_say_unknown(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        """回归：旧代码只读 message 字段，而 400 响应常常没有 message，于是打印「未知错误」。"""
        _login_config()
        stub = stub_session(
            {
                CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []}),
                CHECK_KEY: fake_response(200, json_data={"code": 400}),
            }
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        out = capsys.readouterr().out
        assert "未知错误" not in out
        assert "code=400" in out

    def test_empty_response_is_reported_as_no_reply(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = stub_session(
            {
                CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []}),
                CHECK_KEY: fake_response(200, text=""),
            }
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "接口无响应" in capsys.readouterr().out

    def test_token_alloc_error_is_reported(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = stub_session(
            {
                CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []}),
                CHECK_KEY: fake_response(200, json_data={"code": 200, "needUpload": True, "songId": "S1"}),
                TOKEN_KEY: fake_response(200, json_data={"code": 400, "message": "bucket error"}),
            }
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "凭证" in capsys.readouterr().out


class TestUploadToCloudFlow:
    """校验官方 5 步直传链路：check → token → NOS 流 → info/v2 → pub/v2。

    测试直接解密 eapi 的 params，断言真实发出的线上参数，避免「本地看着对、线上被拒」。
    """

    def _stub(self, stub_session, fake_response, **overrides):
        mapping = {
            CLOUD_URL_KEY: fake_response(200, json_data={"code": 200, "data": []}),
            CHECK_KEY: fake_response(200, json_data={"code": 200, "needUpload": True, "songId": "S1"}),
            TOKEN_KEY: fake_response(200, json_data={"code": 200, "result": {
                "bucket": "jd-musicrep-privatecloud-audio-public",
                "token": "UPLOAD fake-token",
                "objectKey": "obj/aa/bb/cccc.flac",
                "docId": -1,
                "resourceId": 82951949783,
            }}),
            LBS_KEY: fake_response(200, json_data={"upload": ["http://upload.example.com"]}),
            NOS_HOST_KEY: fake_response(200, text=""),
            INFO_KEY: fake_response(200, json_data={
                "code": 200, "songId": "3436477678", "exists": True,
                "privateCloud": {"simpleSong": {"id": 3436477678}},
            }),
            PUB_KEY: fake_response(200, json_data={"code": 200, "songId": "3436477678"}),
        }
        mapping.update(overrides)
        return stub_session(mapping)

    def _payloads(self, stub, key):
        """从 stub 记录的调用里取出命中的 eapi 明文参数。"""
        out = []
        for method, url, kwargs in stub.calls:
            if key in url and "params" in kwargs.get("data", {}):
                out.append(_decode_eapi_payload(kwargs["data"]["params"]))
        return out

    def test_happy_path_covers_all_five_steps(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = self._stub(stub_session, fake_response)
        client = _client(monkeypatch, stub)
        f = tmp_path / "许嵩 - 断桥残雪.flac"
        f.write_bytes(b"audio-bytes")

        assert client.upload_to_cloud(str(f), "断桥残雪", "许嵩", "") is True
        out = capsys.readouterr().out
        assert "上传成功" in out

        # NOS 直传用的是 objectKey（且 `/` 转义）而不是 docId=-1
        nos_calls = [u for _, u, _ in stub.calls if "upload.example.com" in u]
        assert len(nos_calls) == 1
        assert "obj%2Faa%2Fbb%2Fcccc.flac" in nos_calls[0]
        assert "/-1?" not in nos_calls[0]

        # info/v2 必须回带真实的 resourceId 和 check 返回的 songid
        info = self._payloads(stub, "api/upload/cloud/info/v2")[-1]
        data = json.loads(info[1])
        assert data["resourceId"] == 82951949783
        assert data["songid"] == "S1"
        assert data["md5"] == hashlib.md5(b"audio-bytes").hexdigest()

        # 发布步骤必须存在，且用 info/v2 返回的新 songId
        pub = self._payloads(stub, "api/cloud/pub/v2")[-1]
        assert json.loads(pub[1])["songid"] == "3436477678"

    def test_check_params_are_flat_not_songs_array(self, monkeypatch, stub_session, fake_response, tmp_path):
        """回归：早期实现发的是 songs 数组，服务端会回 400 参数错误。"""
        _login_config()
        stub = self._stub(stub_session, fake_response)
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.flac"
        f.write_bytes(b"x" * 10)

        assert client.upload_to_cloud(str(f), "t", "a", "al") is True
        data = json.loads(self._payloads(stub, "api/cloud/upload/check")[-1][1])
        assert "songs" not in data
        assert data["md5"] == hashlib.md5(b"x" * 10).hexdigest()
        assert data["length"] == 10
        assert data["songId"] == "0"
        assert data["version"] == 1
        assert data["bitrate"] == "999000"

    def test_need_upload_false_skips_nos_stream(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = self._stub(
            stub_session, fake_response,
            **{CHECK_KEY: fake_response(200, json_data={"code": 200, "needUpload": False, "songId": "S9"})},
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "t", "a", "al") is True
        assert not [u for _, u, _ in stub.calls if "upload.example.com" in u]
        assert not [u for _, u, _ in stub.calls if "wanproxy" in u]
        assert "跳过二进制上传" in capsys.readouterr().out

    def test_info_failure_surfaces_message(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = self._stub(
            stub_session, fake_response,
            **{INFO_KEY: fake_response(200, json_data={"code": 403, "message": "资源不存在"})},
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "资源不存在" in capsys.readouterr().out

    def test_pub_failure_surfaces_message(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = self._stub(
            stub_session, fake_response,
            **{PUB_KEY: fake_response(200, json_data={"code": 500, "message": "发布失败"})},
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "发布失败" in capsys.readouterr().out

    def test_song_fields_are_sanitized(self, monkeypatch, stub_session, fake_response, tmp_path):
        """网易云要求 song/artist/album 不含 '.' 与 '/'，否则提交必然失败。"""
        _login_config()
        stub = self._stub(stub_session, fake_response)
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "A.B/C", "X.Y", "Al/Bum") is True
        data = json.loads(self._payloads(stub, "api/upload/cloud/info/v2")[-1][1])
        assert "." not in data["song"] and "/" not in data["song"]
        assert "/" not in data["artist"]
        assert "/" not in data["album"]

    def test_empty_artist_falls_back_to_placeholder(self, monkeypatch, stub_session, fake_response, tmp_path):
        _login_config()
        stub = self._stub(stub_session, fake_response)
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "t", "", "") is True
        data = json.loads(self._payloads(stub, "api/upload/cloud/info/v2")[-1][1])
        assert data["artist"] == "未知艺术家"
        assert data["album"] == "未知专辑"

    def test_nos_upload_failure_aborts_before_info(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = self._stub(
            stub_session, fake_response,
            **{NOS_HOST_KEY: fake_response(403, text="denied")},
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "NOS 音频流上传失败" in capsys.readouterr().out
        assert not self._payloads(stub, "api/upload/cloud/info/v2")

    def test_lbs_without_host_is_reported(self, monkeypatch, stub_session, fake_response, tmp_path, capsys):
        _login_config()
        stub = self._stub(
            stub_session, fake_response,
            **{LBS_KEY: fake_response(200, json_data={"upload": []})},
        )
        client = _client(monkeypatch, stub)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")

        assert client.upload_to_cloud(str(f), "t", "a", "al") is False
        assert "获取 NOS 上传节点失败" in capsys.readouterr().out
