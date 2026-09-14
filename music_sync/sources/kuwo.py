import ast
from typing import List

from rich.console import Console

from music_sync.http import get_session
from music_sync.sources.base import BaseSource, TrackCandidate
from music_sync.validator import check_blacklist, validate_candidate_match, validate_duration

console = Console()


class KuwoMusicSource(BaseSource):
    @property
    def name(self) -> str:
        return "kuwo"

    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        session = get_session()
        query = f"{title} {artist}".strip()
        search_url = "http://search.kuwo.cn/r.s"
        params = {
            "all": query,
            "ft": "music",
            "itemset": "web_2013",
            "client": "kt",
            "pn": 0,
            "rn": 30,
            "rformat": "json",
            "encoding": "utf8"
        }
        candidates = []
        try:
            resp = session.get(search_url, params=params, timeout=8)
        except Exception as e:
            console.print(f"      [yellow]↳ KUWO 搜索请求失败: {e}[/yellow]")
            return candidates

        if resp.status_code != 200:
            console.print(f"      [yellow]↳ KUWO 搜索返回 HTTP {resp.status_code}[/yellow]")
            return candidates

        # 该接口返回的是单引号包裹的 Python 字面量，不是标准 JSON，
        # 直接 resp.json() 必然抛 JSONDecodeError，这里回退到 literal_eval。
        data = None
        try:
            data = resp.json()
        except ValueError:
            try:
                data = ast.literal_eval(resp.text)
            except (ValueError, SyntaxError) as e:
                console.print(f"      [yellow]↳ KUWO 响应解析失败: {e}[/yellow]")
                return candidates

        abslist = data.get("abslist", []) if isinstance(data, dict) else []
        for item in abslist:
            # KUWO 老接口返回的文本带 HTML 实体和转义字符，先清洗
            song_name = item.get("SONGNAME", "").replace("&nbsp;", " ").strip()
            singer = (item.get("ARTIST", "")
                      .replace("\\u0026", "&")
                      .replace("\\/", "/")
                      .replace("&nbsp;", " ")
                      .strip())
            album = item.get("ALBUM", "")
            music_rid = str(item.get("MUSICRID", "")).replace("MUSIC_", "")
            try:
                duration = int(item.get("DURATION", 0))
            except (TypeError, ValueError):
                duration = 0

            if not song_name or not music_rid:
                continue

            # 严格校验歌名与歌手，避免命中翻唱/串烧
            if not validate_candidate_match(song_name, singer, title, artist):
                continue

            is_bl, _ = check_blacklist(f"{song_name} {album}")
            if is_bl:
                continue

            if not validate_duration(duration, target_duration):
                continue

            play_url = (
                "http://antiserver.kuwo.cn/anti.s"
                f"?type=convert_url&rid={music_rid}&format=mp3&response=url"
            )
            try:
                p_resp = session.get(play_url, timeout=5)
            except Exception:
                continue
            if p_resp.status_code == 200 and p_resp.text.strip().startswith("http"):
                candidates.append(TrackCandidate(
                    source="kuwo",
                    song_id=music_rid,
                    title=song_name,
                    artist=singer,
                    album=album,
                    duration_seconds=duration,
                    quality="320k",
                    file_ext="mp3",
                    download_url=p_resp.text.strip()
                ))
        if not candidates and abslist:
            console.print(
                f"      [yellow]↳ KUWO: 搜索到 {len(abslist)} 条，无匹配曲目或无可用直链[/yellow]"
            )
        return candidates
