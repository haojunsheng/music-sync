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
            s_name = pc.get("songName", pc.get("song", "")).lower()
            a_name = pc.get("artist", "").lower()
            if title_lower in s_name and (not artist_lower or artist_lower in a_name):
                return True
        return False

    def upload_to_cloud(self, file_path: str, title: str, artist: str, album: str) -> bool:
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

        # Step 1: 上传检查（eapi；weapi 已下线，返回 200 + 空 body）
        check_data = {
            "uploadType": 0,
            "songs": json.dumps([{
                "md5": md5_hex,
                "songId": "0",
                "filename": os.path.basename(file_path),
                "song": title,
                "artist": artist,
                "album": album,
                "bitrate": "320000",
                "ext": ext
            }])
        }
        check_res = self.eapi_request("/api/cloud/upload/check", check_data)
        # 接口异常时 data 可能为 null，直接取 [0] 会抛 TypeError
        check_items = check_res.get("data") or [{}]
        need_upload = check_items[0].get("needUpload", True)
        song_id = check_items[0].get("songId", "")

        if not need_upload and song_id:
            # 云盘秒传
            console.print("[green]云端已存在相同音频，触发秒传完成！[/green]")
            return True

        # Step 2: 申请 NOS 上传凭证（eapi）
        token_data = {
            "bucket": "jd-musicrep-privatecloud-audio-public",
            "ext": ext,
            "filename": os.path.basename(file_path),
            "local": False,
            "nos_product": 3,
            "type": "audio",
            "md5": md5_hex
        }
        token_res = self.eapi_request("/api/nos/token/alloc", token_data)
        result_info = token_res.get("result", {})
        doc_id = result_info.get("docId")
        token = result_info.get("token")
        bucket = result_info.get("bucket", "jd-musicrep-privatecloud-audio-public")

        if not token or not doc_id:
            console.print("[red]获取 NOS 上传凭证失败[/red]")
            return False

        # Step 3: Direct binary upload to NOS
        nos_url = f"https://interface.music.163.com/nos-upload/{bucket}/{doc_id}?offset=0&complete=true&version=1.0"
        headers = {
            "x-nos-token": token,
            "Content-Type": "audio/mpeg" if ext == "mp3" else "audio/flac",
            "Content-MD5": md5_hex
        }
        upload_resp = self.session.post(nos_url, data=content, headers=headers, timeout=60)
        if upload_resp.status_code not in (200, 201):
            console.print(f"[red]NOS 音频流上传失败 (HTTP {upload_resp.status_code})[/red]")
            return False

        # Step 4: 发布到用户云盘（eapi）
        pub_data = {
            "md5": md5_hex,
            "songid": "0",
            "filename": os.path.basename(file_path),
            "song": title,
            "artist": artist,
            "album": album,
            "bitrate": "320000",
            "resourceId": doc_id
        }
        pub_res = self.eapi_request("/api/upload/cloud/info/v2", pub_data)

        if pub_res.get("code") == 200:
            console.print(f"[bold green]上传成功！已同步至网易云云盘: {title} - {artist}[/bold green]")
            return True
        else:
            console.print(f"[red]云盘提交失败: {pub_res.get('message', '未知错误')}[/red]")
            return False

def login_qr() -> bool:
    client = NetEaseClient()
    return client.login_with_qrcode()
