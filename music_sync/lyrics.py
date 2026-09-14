import re
import base64
from typing import Optional, Tuple

from music_sync.config import load_config
from music_sync.http import get_session
from music_sync.netease_crypto import eapi_encrypt

EAPI_HOST = "https://interface.music.163.com/eapi"
# 注意：必须用不带 /v1 的路径。/api/song/lyric/v1 返回的是逐字歌词 JSON
# （形如 {"t":0,"c":[{"tx":"..."}]} 每行一个对象），不是标准 LRC 时间轴。
NETEASE_LYRIC_PATH = "/api/song/lyric"


def parse_last_lyric_timestamp(lrc_text: str) -> float:
    matches = re.findall(r'\[(\d{2}):(\d{2}(?:\.\d+)?)\]', lrc_text)
    if not matches:
        return 0.0
    last_m, last_s = matches[-1]
    return int(last_m) * 60 + float(last_s)

def fetch_qq_lyrics(songmid: str) -> Optional[str]:
    session = get_session()
    url = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    params = {
        "songmid": songmid,
        "format": "json",
        "nobase64": 0
    }
    headers = {"Referer": "https://y.qq.com/"}
    try:
        resp = session.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            lyric_b64 = data.get("lyric", "")
            if lyric_b64:
                return base64.b64decode(lyric_b64).decode("utf-8", errors="ignore")
    except Exception:
        pass
    return None

def fetch_netease_lyrics(title: str, artist: str) -> Optional[str]:
    """经 eapi 获取网易云歌词。

    旧实现走 weapi/crypto/song/lyric，该通道已下线（返回 200 + 空 body），
    表现为「歌词: 无」。现改为 eapi，并携带登录态 Cookie。
    """
    session = get_session()
    cookie = load_config().netease_cookie or ""

    # 1) 先按歌名/歌手搜出 song id
    search_url = "https://music.163.com/api/search/get/web"
    params = {"s": f"{title} {artist}", "type": 1, "limit": 1}
    try:
        resp = session.get(search_url, params=params, timeout=8)
        if resp.status_code != 200:
            return None
        songs = resp.json().get("result", {}).get("songs", [])
        if not songs:
            return None
        song_id = songs[0].get("id")
    except Exception:
        return None

    # 2) eapi 取歌词
    try:
        encrypted = eapi_encrypt(NETEASE_LYRIC_PATH, {"id": song_id, "lv": -1, "tv": -1})
        lrc_resp = session.post(
            EAPI_HOST + NETEASE_LYRIC_PATH,
            data={"params": encrypted},
            headers={"Referer": "https://music.163.com", "Cookie": cookie},
            timeout=8,
        )
        if lrc_resp.status_code == 200:
            return lrc_resp.json().get("lrc", {}).get("lyric", "")
    except Exception:
        pass
    return None

def get_lyrics(title: str, artist: str, qq_songmid: str = "", expected_duration: int = 0) -> Tuple[str, bool]:
    lrc = ""
    if qq_songmid:
        lrc = fetch_qq_lyrics(qq_songmid) or ""

    if not lrc:
        lrc = fetch_netease_lyrics(title, artist) or ""

    if not lrc:
        return "", False

    # Timestamp consistency check
    if expected_duration > 0:
        last_ts = parse_last_lyric_timestamp(lrc)
        # Last lyric should generally be within 40 seconds before or slightly after audio end
        if last_ts > 0 and abs(expected_duration - last_ts) > 60 and last_ts > expected_duration + 10:
            return lrc, False

    return lrc, True
