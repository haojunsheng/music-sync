import base64
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
