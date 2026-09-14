import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
import qrcode
from rich.console import Console

from music_sync.config import DEFAULT_COOKIE_FILE, load_config
from music_sync.http import DEFAULT_USER_AGENT, get_session
from music_sync.netease_crypto import eapi_encrypt, weapi_encrypt

console = Console()

# 网易云个人云盘（private cloud）上传通道使用的固定常量。
CLOUD_BUCKET = "jd-musicrep-privatecloud-audio-public"
# NOS 上传节点是动态下发的，不能写死；必须先向 wanproxy 询问本次可用的上传域名。
NOS_LBS_URL = "https://wanproxy.127.net/lbs?version=1.0&bucketname={bucket}"
# 无损档位固定上报 999000，有损兜底上报 320000（与官方客户端一致）。
CLOUD_LOSSLESS_BITRATE = "999000"
CLOUD_LOSSY_BITRATE = "320000"
CLOUD_LOSSLESS_EXT = ("flac", "ape", "wav")
# info/v2 的 album 为空时官方会填「未知专辑」
DEFAULT_CLOUD_ALBUM = "未知专辑"


def _clean_cloud_field(value: str, fallback: str) -> str:
    """清洗 info/v2 的 song/artist/album 字段。

    网易云要求这三个字段不得包含 `.` 与 `/`，否则提交直接失败。
    """
    cleaned = (value or "").replace(".", " ").replace("/", " ").strip()
    return cleaned or fallback


def _encode_object_key(object_key: str) -> str:
    """NOS 上传路径里的 objectKey 必须把 `/` 转义成 %2F，否则会被当成多级目录。"""
    return object_key.replace("/", "%2F")


def _cloud_bitrate(ext: str) -> str:
    return CLOUD_LOSSLESS_BITRATE if ext in CLOUD_LOSSLESS_EXT else CLOUD_LOSSY_BITRATE


def _describe_api_error(res: Dict[str, Any]) -> str:
    """把网易云的失败响应翻译成可读原因。

    网易云不少失败响应只有 code 没有 message（例如 info/v2 的 400），
    直接取 message 会退化成「未知错误」，排查时毫无信息量。
    """
    if not res:
        return "接口无响应（网络异常或 Cookie 已失效）"
    for key in ("message", "msg", "error"):
        if res.get(key):
            return str(res[key])
    code = res.get("code")
    return f"接口返回 code={code}，无附加信息" if code is not None else "接口返回内容无法解析"

class NetEaseClient:
    def __init__(self):
        self.session = get_session()
        self.cookie_file = DEFAULT_COOKIE_FILE
        self.cookies: Dict[str, str] = {}
        self._load_cookies()

    def _load_cookies(self):
        cfg = load_config()
        if cfg.netease_cookie:
            # Parse from config
            for item in cfg.netease_cookie.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    self.cookies[k] = v
                    self.session.cookies.set(k, v, domain=".music.163.com")

        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    file_cookies = json.load(f)
                    self.cookies.update(file_cookies)
                    for k, v in self.cookies.items():
                        self.session.cookies.set(k, v, domain=".music.163.com")
            except Exception:
                pass

    def save_cookies(self):
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        # Extract cookies from session
        for c in self.session.cookies:
            if "163.com" in c.domain or not c.domain:
                self.cookies[c.name] = c.value
        with open(self.cookie_file, "w", encoding="utf-8") as f:
            json.dump(self.cookies, f, ensure_ascii=False, indent=2)

    def weapi_request(self, url: str, data: dict) -> dict:
        csrf = self.cookies.get("__csrf", "")
        if "csrf_token" not in data:
            data["csrf_token"] = csrf
        if "?" not in url and csrf:
            url = f"{url}?csrf_token={csrf}"
        encrypted = weapi_encrypt(data)
        headers = {
            "Referer": "https://music.163.com",
            "Origin": "https://music.163.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        try:
            resp = self.session.post(url, data=encrypted, headers=headers, timeout=15)
            if resp.status_code == 200 and resp.text:
                return resp.json()
        except Exception:
            pass
        return {}

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def eapi_request(self, path: str, data: dict) -> dict:
        """eapi 通道请求。weapi 已被服务端下线（返回 200 + 空 body）。

        path 形如 /api/cloud/upload/check；任何异常一律返回 {}。
        """
        try:
            resp = self.session.post(
                "https://interface.music.163.com/eapi" + path,
                data={"params": eapi_encrypt(path, data)},
                headers={
                    "Referer": "https://music.163.com",
                    "Origin": "https://music.163.com",
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Cookie": self._cookie_header(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=15,
            )
            if resp.status_code == 200 and resp.text:
                return resp.json()
        except Exception:
            pass
        return {}

    def api_request(self, url: str, data: dict = None) -> dict:
        headers = {
            "Referer": "https://music.163.com",
            "Origin": "https://music.163.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = self.session.post(url, data=data or {}, headers=headers, timeout=15)
            if resp.status_code == 200 and resp.text:
                return resp.json()
        except Exception:
            pass
        return {}

    def get_login_qr_key(self) -> Optional[str]:
        # 1. 尝试标准 API 接口
        try:
            url = "https://music.163.com/api/login/qrcode/unikey"
            headers = {
                "Referer": "https://music.163.com",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = self.session.post(url, data={"type": 1}, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.text:
                res = resp.json()
                if res.get("code") == 200 and res.get("unikey"):
                    return res.get("unikey")
        except Exception:
            pass

        # 2. 兜底 weapi 接口
        try:
            url = "https://music.163.com/weapi/login/qrcode/unikey?csrf_token="
            data = {"type": 1, "csrf_token": ""}
            res = self.weapi_request(url, data)
            if res.get("unikey"):
                return res.get("unikey")
        except Exception:
            pass
        return None

    def check_qr_status(self, unikey: str) -> dict:
        headers = {
            "Referer": "https://music.163.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 优先使用 api 接口查询状态
        try:
            url = "https://music.163.com/api/login/qrcode/client/login"
            resp = self.session.post(url, data={"key": unikey, "type": 1}, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.text:
                return resp.json()
        except Exception:
            pass

        # 兜底 weapi 查询
        try:
            url = "https://music.163.com/weapi/login/qrcode/client/login?csrf_token="
            data = {"key": unikey, "type": 1, "csrf_token": ""}
            return self.weapi_request(url, data)
        except Exception:
            return {}

    def login_with_qrcode(self, timeout_sec: int = 120) -> bool:
        unikey = self.get_login_qr_key()
        if not unikey:
            console.print("[red]获取登录二维码失败！[/red]")
            return False

        qr_url = f"https://music.163.com/login?codekey={unikey}"
        qr = qrcode.QRCode()
        qr.add_data(qr_url)
        qr.make(fit=True)

        console.print("[cyan]请打开网易云音乐 App 扫描以下二维码登录：[/cyan]")
        qr.print_ascii(invert=True)
        console.print(f"[dim]二维码链接: {qr_url}[/dim]")

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            status_res = self.check_qr_status(unikey)
            code = status_res.get("code")
            if code == 800:
                console.print("[red]二维码已过期，请重新登录！[/red]")
                return False
            elif code == 801:
                # 等待扫码
                time.sleep(2)
            elif code == 802:
                console.print("[yellow]已扫码，等待在手机上确认授权...[/yellow]")
                time.sleep(2)
            elif code == 803:
                console.print("[green]授权成功，登录完成！[/green]")
                self.save_cookies()
                return True
            else:
                time.sleep(2)
        console.print("[red]登录超时！[/red]")
        return False

    def is_logged_in(self) -> bool:
        if "MUSIC_U" in self.cookies:
            res = self.api_request("https://music.163.com/api/v1/cloud/get", {"limit": 1, "offset": 0})
            if "code" in res and res.get("code") == 200:
                return True
            if "data" in res:
                return True
        return False

    def check_cloud_song_exists(self, title: str, artist: str) -> bool:
        if not self.is_logged_in():
            return False
        res = self.api_request("https://music.163.com/api/v1/cloud/get", {"limit": 200, "offset": 0})
        songs = res.get("data", [])
        title_lower = title.lower()
        artist_lower = artist.lower()
        for item in songs:
            pc = item.get("privateCloud", item)
            # 真实响应里歌名字段叫 song（songName/fileName 是历史或其它端写入口径）
            s_name = (pc.get("songName") or pc.get("song") or pc.get("fileName") or "").lower()
            a_name = (pc.get("artist") or "").lower()
            if title_lower in s_name and (not artist_lower or artist_lower in a_name):
                return True
        return False

    def _upload_stream_to_nos(self, object_key: str, token: str, md5_hex: str,
                              content: bytes, ext: str) -> bool:
        """把音频二进制流直传到 NOS。

        节点地址由 wanproxy 的 lbs 接口动态下发，URL 形如
        `<上传域名>/<bucket>/<objectKey 转义后>?offset=0&complete=true&version=1.0`。
        """
        try:
            lbs_resp = self.session.get(NOS_LBS_URL.format(bucket=CLOUD_BUCKET), timeout=15)
            lbs = lbs_resp.json()
        except Exception as e:
            console.print(f"[red]获取 NOS 上传节点失败: {e}[/red]")
            return False

        hosts = lbs.get("upload") or []
        if not hosts:
            console.print("[red]获取 NOS 上传节点失败: lbs 未返回可用域名[/red]")
            return False

        nos_url = (
            f"{hosts[0]}/{CLOUD_BUCKET}/{_encode_object_key(object_key)}"
            "?offset=0&complete=true&version=1.0"
        )
        headers = {
            "x-nos-token": token,
            "Content-MD5": md5_hex,
            "Content-Type": f"audio/{ext}" if ext in CLOUD_LOSSLESS_EXT + ("mp3",) else "audio/mpeg",
            "Content-Length": str(len(content)),
        }
        try:
            upload_resp = self.session.post(nos_url, data=content, headers=headers, timeout=180)
        except Exception as e:
            console.print(f"[red]NOS 音频流上传异常: {e}[/red]")
            return False

        if upload_resp.status_code not in (200, 201):
            console.print(f"[red]NOS 音频流上传失败 (HTTP {upload_resp.status_code})[/red]")
            return False
        return True

    def upload_to_cloud(self, file_path: str, title: str, artist: str, album: str) -> bool:
        """把本地文件同步进网易云个人云盘。

        官方云盘直传共 5 步，缺任何一步都不会出现在「我的云盘」里：
          1. /api/cloud/upload/check        —— 用 md5 换 needUpload + songId
          2. /api/nos/token/alloc           —— 换 NOS token / objectKey / resourceId
          3. NOS 直传二进制流（needUpload 为 true 时才需要）
          4. /api/upload/cloud/info/v2      —— 登记资源元信息，拿新 songId
          5. /api/cloud/pub/v2              —— 发布到个人云盘（这一步不能省）
        """
        if not self.is_logged_in():
            console.print("[red]网易云未登录或 Cookie 失效，请先执行: python -m music_sync login[/red]")
            return False

        if not os.path.exists(file_path):
            console.print(f"[red]文件不存在: {file_path}[/red]")
            return False

        file_size = os.path.getsize(file_path)
        ext = Path(file_path).suffix.lstrip(".").lower()
        if ext == "ape":
            console.print("[yellow]网易云云盘不支持 APE 格式，已跳过上传[/yellow]")
            return False

        import hashlib
        with open(file_path, "rb") as f:
            content = f.read()
        md5_hex = hashlib.md5(content).hexdigest()
        bitrate = _cloud_bitrate(ext)

        # 文件名清洗规则与官方客户端一致：去掉扩展名与空格，点号换成下划线
        stem = Path(file_path).stem.replace(" ", "").replace(".", "_") or "audio"

        # Step 1: 上传检查。注意参数是扁平结构（早期的 songs 数组写法服务端会回 400 参数错误）
        check_res = self.eapi_request("/api/cloud/upload/check", {
            "bitrate": bitrate,
            "ext": "",
            "length": file_size,
            "md5": md5_hex,
            "songId": "0",
            "version": 1,
        })
        if check_res.get("code") != 200:
            console.print(f"[red]云盘上传检查失败: {_describe_api_error(check_res)}[/red]")
            return False

        need_upload = check_res.get("needUpload", True)
        # songId 是「这个 md5 在云端的资源 id」，登记步骤必须原样带回
        cloud_song_id = check_res.get("songId") or "0"

        # Step 2: 申请 NOS 上传凭证
        token_res = self.eapi_request("/api/nos/token/alloc", {
            "bucket": "",
            "ext": ext,
            "filename": stem,
            "local": False,
            "nos_product": 3,
            "type": "audio",
            "md5": md5_hex,
        })
        result_info = token_res.get("result") or {}
        token = result_info.get("token")
        object_key = result_info.get("objectKey")
        # resourceId 才是登记接口要的值；docId 在「云端已有同 md5」时会被填成 -1
        resource_id = result_info.get("resourceId")

        if not token or not object_key or resource_id is None:
            console.print(f"[red]获取 NOS 上传凭证失败: {_describe_api_error(token_res)}[/red]")
            return False

        # Step 3: 云端没有同 md5 的音频时才需要推流；否则直接复用已有资源
        if need_upload:
            if not self._upload_stream_to_nos(object_key, token, md5_hex, content, ext):
                return False
            console.print("  [green]✓[/green] 音频流已上传至 NOS")
        else:
            console.print("  [dim]云端已存在相同音频，跳过二进制上传[/dim]")

        # Step 4: 登记云盘资源元信息
        info_res = self.eapi_request("/api/upload/cloud/info/v2", {
            "md5": md5_hex,
            "songid": str(cloud_song_id),
            "filename": stem,
            "song": _clean_cloud_field(title, stem),
            "artist": _clean_cloud_field(artist, "未知艺术家"),
            "album": _clean_cloud_field(album, DEFAULT_CLOUD_ALBUM),
            "bitrate": bitrate,
            "resourceId": resource_id,
        })
        if info_res.get("code") != 200:
            console.print(f"[red]云盘资源登记失败: {_describe_api_error(info_res)}[/red]")
            return False

        new_song_id = info_res.get("songId") or (
            (info_res.get("privateCloud") or {}).get("simpleSong") or {}
        ).get("id")
        if not new_song_id:
            console.print("[red]云盘资源登记失败: 接口未返回 songId[/red]")
            return False

        # Step 5: 发布到个人云盘（少了这一步，资源只登记不展示）
        pub_res = self.eapi_request("/api/cloud/pub/v2", {"songid": str(new_song_id)})
        if pub_res.get("code") != 200 and not pub_res.get("privateCloud"):
            console.print(f"[red]云盘发布失败: {_describe_api_error(pub_res)}[/red]")
            return False

        console.print(f"[bold green]上传成功！已同步至网易云云盘: {title} - {artist}[/bold green]")
        return True

def login_qr() -> bool:
    client = NetEaseClient()
    return client.login_with_qrcode()
