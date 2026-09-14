"""歌手热门歌曲列表获取。

优先 QQ 音乐（华语曲库覆盖最全），失败时回退网易云。
对外只暴露 get_artist_top_songs()，返回统一的 [{title, artist, album, duration}]。
"""
import json
from typing import Dict, List, Optional

from rich.console import Console

from music_sync.config import load_config
from music_sync.http import get_session

console = Console()

QQ_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_SINGER_DETAIL_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
NETEASE_SEARCH_URL = "https://music.163.com/api/search/get/web"
NETEASE_ARTIST_TOP_URL = "https://music.163.com/api/artist/top/song"

# QQ 歌手详情排序：5 = 按热度
QQ_SORT_HOT = 5


def _artist_matches(candidate: str, target: str) -> bool:
    if not candidate or not target:
        return False
    c, t = candidate.strip(), target.strip()
    return c == t or c in t or t in c


def search_qq_singer_mid(session, artist: str) -> Optional[str]:
    """通过歌曲搜索反查歌手 mid（搜索结果里带 singer[].mid）。"""
    try:
        resp = session.get(
            QQ_SEARCH_URL,
            params={"p": 1, "n": 10, "w": artist, "format": "json", "t": 0, "cr": 1},
            headers={"Referer": "https://y.qq.com/"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        songs = resp.json().get("data", {}).get("song", {}).get("list", [])
    except Exception:
        return None

    fallback = None
    for song in songs:
        for singer in song.get("singer", []):
            mid = singer.get("mid")
            name = singer.get("name", "")
            if not mid:
                continue
            if name == artist:
                return mid
            if fallback is None and _artist_matches(name, artist):
                fallback = mid
    return fallback


def fetch_qq_artist_songs(session, singer_mid: str, limit: int) -> List[Dict]:
    """取 QQ 音乐歌手热门歌曲（sort=5 按热度）。"""
    body = {
        "comm": {"ct": 24, "cv": 0},
        "req": {
            "module": "music.web_singer_info_svr",
            "method": "get_singer_detail_info",
            "param": {"sort": QQ_SORT_HOT, "singermid": singer_mid, "sin": 0, "num": limit},
        },
    }
    try:
        resp = session.post(
            QQ_SINGER_DETAIL_URL,
            data=json.dumps(body),
            headers={"Referer": "https://y.qq.com/"},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json().get("req") or {}
        song_list = (payload.get("data") or {}).get("songlist") or []
    except Exception:
        return []

    out = []
    for item in song_list[:limit]:
        title = item.get("name") or item.get("title") or ""
        if not title:
            continue
        out.append({
            "title": title,
            "artist": "/".join(s.get("name", "") for s in (item.get("singer") or [])),
            "album": (item.get("album") or {}).get("name", ""),
            "duration": item.get("interval", 0),
        })
    return out


def search_netease_artist_id(session, cookie: str, artist: str) -> Optional[int]:
    try:
        resp = session.get(
            NETEASE_SEARCH_URL,
            params={"s": artist, "type": 100, "limit": 5},
            headers={"Referer": "https://music.163.com", "Cookie": cookie},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        artists = (resp.json().get("result") or {}).get("artists") or []
    except Exception:
        return None

    for a in artists:
        if a.get("name") == artist:
            return a.get("id")
    return artists[0].get("id") if artists else None


def fetch_netease_artist_songs(session, cookie: str, artist_id: int, limit: int) -> List[Dict]:
    """取网易云歌手热门歌曲（接口本身即按热度返回）。"""
    try:
        resp = session.get(
            NETEASE_ARTIST_TOP_URL,
            params={"id": artist_id},
            headers={"Referer": "https://music.163.com", "Cookie": cookie},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        songs = resp.json().get("songs") or []
    except Exception:
        return []

    out = []
    for s in songs[:limit]:
        title = s.get("name", "")
        if not title:
            continue
        out.append({
            "title": title,
            "artist": "/".join(a.get("name", "") for a in (s.get("ar") or [])),
            "album": (s.get("al") or {}).get("name", ""),
            "duration": round((s.get("dt") or 0) / 1000),
        })
    return out


def get_artist_top_songs(artist: str, limit: int = 50) -> List[Dict]:
    """返回歌手热门歌曲 [{title, artist, album, duration}]；获取失败返回 []。"""
    if limit <= 0:
        return []

    session = get_session()
    cookie = load_config().netease_cookie or ""

    singer_mid = search_qq_singer_mid(session, artist)
    if singer_mid:
        songs = fetch_qq_artist_songs(session, singer_mid, limit)
        if songs:
            console.print(f"  [green]✓[/green] 歌单来源: [bold]QQ 音乐[/bold] (mid={singer_mid})")
            return songs
        console.print("  [yellow]↳ QQ 音乐未返回歌单，改用网易云...[/yellow]")
    else:
        console.print("  [yellow]↳ 未在 QQ 音乐定位到该歌手，改用网易云...[/yellow]")

    artist_id = search_netease_artist_id(session, cookie, artist)
    if artist_id:
        songs = fetch_netease_artist_songs(session, cookie, artist_id, limit)
        if songs:
            console.print(f"  [green]✓[/green] 歌单来源: [bold]网易云[/bold] (id={artist_id})")
            return songs

    return []
