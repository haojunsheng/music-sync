"""pytest 公共夹具。

两条硬约束：
1. 测试全程离线 —— 所有 HTTP 调用由 StubSession 打桩，不访问真实网络。
2. 测试不得读写用户真实的 ~/.config/music-sync/ —— autouse fixture 会把配置与凭据
   文件路径重定向到 tmp_path，避免污染用户本机配置。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeResponse:
    """模拟 requests.Response 的最小实现。"""

    def __init__(self, status_code=200, json_data=None, text=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self._text = text
        self.content = content

    @property
    def text(self):
        if self._text is not None:
            return self._text
        if self._json is not None:
            return json.dumps(self._json, ensure_ascii=False)
        return ""

    def json(self):
        if self._json is None:
            # 模拟空 body / 非 JSON 响应，触发调用方的 ValueError 分支
            raise ValueError("stub response is not JSON")
        return self._json

    def iter_content(self, chunk_size=1):
        """供 download_file 的 stream=True 路径使用。"""
        if self.content:
            yield self.content


class FakeCookies:
    """极简 cookie 容器，供 NetEaseClient 使用。"""

    def __init__(self):
        self._data = {}

    def set(self, name, value, domain=None):
        self._data[name] = value

    def get(self, name, default=None):
        return self._data.get(name, default)

    def __contains__(self, name):
        return name in self._data

    def __iter__(self):
        return iter([])


class StubSession:
    """按 URL 子串匹配返回预置响应的假 session。

    用法::

        s = StubSession({"c.y.qq.com/soso": FakeResponse(json_data={...})})
        monkeypatch.setattr("music_sync.sources.qq.get_session", lambda *a, **k: s)

    mapping 的值可以是 FakeResponse，也可以是可调用对象
    ``fn(method, url, kwargs) -> FakeResponse``，用于按请求体返回不同响应
    （例如 QQ 的 vkey 接口需要按 flac/128k 文件名分别应答）。
    """

    def __init__(self, mapping=None, default=None):
        self.mapping = dict(mapping or {})
        self.default = default if default is not None else FakeResponse(404, text="stub: unmatched url")
        self.calls = []
        self.headers = {}
        self.cookies = FakeCookies()

    def _pick(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        for key, resp in self.mapping.items():
            if key in url:
                return resp(method, url, kwargs) if callable(resp) else resp
        return self.default

    def get(self, url, **kwargs):
        return self._pick("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._pick("POST", url, kwargs)


@pytest.fixture
def stub_session():
    """返回 StubSession 类，测试内自行实例化。"""
    return StubSession


@pytest.fixture
def fake_response():
    return FakeResponse


@pytest.fixture
def patch_session(monkeypatch):
    """把指定模块的 get_session 替换为返回给定 stub 的桩函数。"""

    def _patch(module_attr: str, session):
        monkeypatch.setattr(module_attr, lambda *args, **kwargs: session)

    return _patch


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """把配置/凭据文件全部重定向到临时目录（autouse，全测试生效）。"""
    import music_sync.config as config_mod

    cfg_dir = tmp_path / "music-sync-config"
    fake_config = cfg_dir / "config.json"
    fake_cookie = cfg_dir / "netease_cookie.json"

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_FILE", fake_config)
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_FILE", fake_cookie)

    # netease.py 在模块级直接 import 了 DEFAULT_COOKIE_FILE，需单独打桩
    try:
        import music_sync.netease as ne_mod
        monkeypatch.setattr(ne_mod, "DEFAULT_COOKIE_FILE", fake_cookie)
    except Exception:
        pass

    return cfg_dir
