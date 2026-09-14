import json
import re
from typing import List
from rich.console import Console
from music_sync.http import get_session
from music_sync.config import load_config
from music_sync.validator import check_blacklist, validate_duration, validate_candidate_match
from music_sync.sources.base import BaseSource, TrackCandidate

console = Console()

class QQMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "qq"

    def _parse_cookie(self, cookie_str: str) -> dict:
        cookies = {}
        if not cookie_str:
            return cookies
        for item in cookie_str.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v
        return cookies

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        cfg = load_config()
        session = get_session()
        cookie_dict = self._parse_cookie(cfg.qq_cookie)
        uin = cookie_dict.get("uin", "")
        if uin.startswith("o"):
            uin = uin[1:]

        query = f"{title} {artist}".strip()
        search_url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        params = {
            "p": 1,
            "n": 10,
            "w": query,
            "format": "json",
            "t": 0,
            "cr": 1
        }

        try:
            resp = session.get(search_url, params=params, cookies=cookie_dict, timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
            song_list = data.get("data", {}).get("song", {}).get("list", [])
        except Exception:
            return []

        candidates = []
        vip_songs = []
        for song in song_list:
            song_name = song.get("songname", "")
            singer_list = song.get("singer", [])
            singer_name = "/".join(s.get("name", "") for s in singer_list)
            album_name = song.get("albumname", "")
            interval = song.get("interval", 0)
            songmid = song.get("songmid", "")

            # 歌名/歌手匹配校验：避免把翻唱（如"柔情版-沐萧"）当作原唱
            if not validate_candidate_match(song_name, singer_name, title, artist):
                continue

            is_bl, _ = check_blacklist(f"{song_name} {album_name}")
            if is_bl:
                continue

            if not validate_duration(interval, target_duration):
                continue

            # Check available formats
            # QQ Music quality file prefixes
            file_types = [
                ("F000", "flac", "flac"),
                ("A000", "ape", "ape"),
                ("M800", "320k", "mp3"),
                ("M500", "128k", "mp3")
            ]

            guid = "10000000"
            hit = False
            for prefix, quality, ext in file_types:
                filename = f"{prefix}{songmid}.{ext}"
                post_data = {
                    "req_1": {
                        "module": "vkey.GetVkeyServer",
                        "method": "CgiGetVkey",
                        "param": {
                            "guid": guid,
                            "songmid": [songmid],
                            "songtype": [0],
                            "uin": uin if uin else "0",
                            "loginflag": 1 if uin else 0,
                            "platform": "20",
                            "filename": [filename]
                        }
                    },
                    "comm": {
                        "uin": uin if uin else "0",
                        "format": "json",
                        "ct": 24,
                        "cv": 0
                    }
                }
                try:
                    vkey_resp = session.post(
                        "https://u.y.qq.com/cgi-bin/musicu.fcg",
                        data=json.dumps(post_data),
                        cookies=cookie_dict,
                        timeout=8
                    )
                    if vkey_resp.status_code == 200:
                        vkey_data = vkey_resp.json()
                        midurlinfo = vkey_data.get("req_1", {}).get("data", {}).get("midurlinfo", [])
                        sip = vkey_data.get("req_1", {}).get("data", {}).get("sip", [])
                        if midurlinfo and midurlinfo[0].get("purl"):
                            purl = midurlinfo[0].get("purl")
                            domain = sip[0] if sip else "https://dl.stream.qqmusic.qq.com/"
                            dl_url = f"{domain}{purl}"
                            candidates.append(TrackCandidate(
                                source="qq",
                                song_id=songmid,
                                title=song_name,
                                artist=singer_name,
                                album=album_name,
                                duration_seconds=interval,
                                quality=quality,
                                file_ext=ext,
                                download_url=dl_url
                            ))
                            hit = True
                            break
                except Exception as e:
                    console.print(f"      [yellow]↳ QQ vkey 请求异常: {e}[/yellow]")
                    continue

            if not hit:
                vip_songs.append(f"{song_name} - {singer_name}")

        if not candidates and vip_songs:
            console.print(
                f"      [yellow]↳ QQ: {len(vip_songs)} 首匹配曲目均未返回可用直链"
                f"（多为 VIP/版权限制，需配置会员 qq_cookie）[/yellow]"
            )

        return candidates
