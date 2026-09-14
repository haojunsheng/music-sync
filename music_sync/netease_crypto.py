import base64
import hashlib
import json
import os
from Crypto.Cipher import AES

MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d81ec4e8c28718def579f72fe7504e570e3e86257743446b"
    "defed2e0af0e0001"
)
NONCE = "0CoJUm6Qyw8W8jud"
PUBKEY = "010001"
LINUX_API_KEY = "rFgSplit!#@#@"

# eapi（现行接口）固定密钥与分隔符；weapi 已废弃但保留以供兼容
EAPI_KEY = "e82ckenh8dichen8"
EAPI_SEP = "-36cd479b6b5-"

def _aes_encrypt(text: str, key: str) -> str:
    pad = 16 - len(text.encode("utf-8")) % 16
    text = text + chr(pad) * pad
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, b"0102030405060708")
    encrypted = cipher.encrypt(text.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def _rsa_encrypt(text: str, pubkey: str, modulus: str) -> str:
    text = text[::-1]
    rs = pow(int(text.encode("utf-8").hex(), 16), int(pubkey, 16), int(modulus, 16))
    return f"{rs:x}".zfill(256)

def weapi_encrypt(data: dict) -> dict:
    text = json.dumps(data, ensure_ascii=False)
    secret_key = os.urandom(16).hex()[:16]
    params = _aes_encrypt(_aes_encrypt(text, NONCE), secret_key)
    enc_sec_key = _rsa_encrypt(secret_key, PUBKEY, MODULUS)
    return {
        "params": params,
        "encSecKey": enc_sec_key
    }

def eapi_encrypt(url_path: str, payload: dict) -> str:
    """网易云 eapi 参数加密，返回可直接作为 params 提交的大写 hex 字符串。

    明文约定为 `nobody{path}use{json}md5forencrypt`；随后把 path、json 与
    该明文的 md5 用分隔符拼起来，整体做 AES-128-ECB（PKCS7 填充）。
    weapi 通道已被服务端下线（返回 200 + 空 body），因此改用 eapi。
    """
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.md5(f"nobody{url_path}use{text}md5forencrypt".encode("utf-8")).hexdigest()
    raw = f"{url_path}{EAPI_SEP}{text}{EAPI_SEP}{digest}"
    pad = 16 - len(raw.encode("utf-8")) % 16
    raw += chr(pad) * pad
    cipher = AES.new(EAPI_KEY.encode("utf-8"), AES.MODE_ECB)
    return cipher.encrypt(raw.encode("utf-8")).hex().upper()
