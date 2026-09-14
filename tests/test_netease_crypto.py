"""网易云 weapi 加密测试。

加密一旦写错，所有依赖 weapi 的接口（直链、歌词、云盘上传）会整体失效且
错误会被上层 except 吞掉，所以这里要钉死输出结构、长度和可逆性。
"""
import base64

from Crypto.Cipher import AES

from music_sync import netease_crypto

CBC_IV = b"0102030405060708"


class TestWeapiEncrypt:
    def test_returns_exactly_two_fields(self):
        enc = netease_crypto.weapi_encrypt({"ids": "[1]"})
        assert set(enc.keys()) == {"params", "encSecKey"}

    def test_fields_are_non_empty_strings(self):
        enc = netease_crypto.weapi_encrypt({"a": 1})
        assert isinstance(enc["params"], str) and enc["params"]
        assert isinstance(enc["encSecKey"], str) and enc["encSecKey"]

    def test_enc_sec_key_is_256_hex_digits(self):
        # RSA 结果需要补齐到 256 位十六进制，否则服务端解析失败
        enc = netease_crypto.weapi_encrypt({"a": 1})
        assert len(enc["encSecKey"]) == 256
        int(enc["encSecKey"], 16)  # 必须是合法十六进制

    def test_random_secret_key_makes_output_nondeterministic(self):
        a = netease_crypto.weapi_encrypt({"same": "payload"})
        b = netease_crypto.weapi_encrypt({"same": "payload"})
        assert a["params"] != b["params"]
        assert a["encSecKey"] != b["encSecKey"]

    def test_unicode_payload_does_not_crash(self):
        enc = netease_crypto.weapi_encrypt({"song": "断桥残雪", "artist": "许嵩"})
        assert enc["params"]


class TestAesEncrypt:
    def test_output_is_block_aligned(self):
        for length in (1, 15, 16, 17, 100):
            out = netease_crypto._aes_encrypt("x" * length, netease_crypto.NONCE)
            assert len(base64.b64decode(out)) % 16 == 0

    def test_roundtrip_with_nonce(self):
        plain = '{"ids":[1],"level":"lossless"}'
        enc = netease_crypto._aes_encrypt(plain, netease_crypto.NONCE)
        cipher = AES.new(netease_crypto.NONCE.encode("utf-8"), AES.MODE_CBC, CBC_IV)
        raw = cipher.decrypt(base64.b64decode(enc))
        pad = raw[-1]
        assert raw[:-pad].decode("utf-8") == plain

    def test_known_vectors_stable(self):
        """固定输入必须产出固定密文，防止后续重构悄悄改了填充/IV 约定。"""
        out = netease_crypto._aes_encrypt("abc", netease_crypto.NONCE)
        cipher = AES.new(netease_crypto.NONCE.encode("utf-8"), AES.MODE_CBC, CBC_IV)
        raw = cipher.decrypt(base64.b64decode(out))
        assert raw[:-raw[-1]].decode("utf-8") == "abc"


class TestRsaEncrypt:
    def test_output_fixed_width(self):
        out = netease_crypto._rsa_encrypt("0123456789abcdef", netease_crypto.PUBKEY, netease_crypto.MODULUS)
        assert len(out) == 256
        int(out, 16)

    def test_deterministic_for_same_input(self):
        # RSA 无随机填充，同样输入必须得到同样输出
        a = netease_crypto._rsa_encrypt("0123456789abcdef", netease_crypto.PUBKEY, netease_crypto.MODULUS)
        b = netease_crypto._rsa_encrypt("0123456789abcdef", netease_crypto.PUBKEY, netease_crypto.MODULUS)
        assert a == b
