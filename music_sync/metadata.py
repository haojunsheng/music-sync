import re
from dataclasses import dataclass
from typing import Optional, List
from music_sync.http import get_session
from music_sync.validator import validate_candidate_match

@dataclass
class OfficialMetadata:
    title: str
    artist: str
    album: str
    duration_seconds: int
    cover_url: str = ""
    release_year: str = ""
    source: str = ""

def fetch_itunes_metadata(title: str, artist: str, regions: List[str] = None) -> Optional[OfficialMetadata]:
    if regions is None:
        regions = ["CN", "TW", "HK", "US"]
    session = get_session()
    query = f"{title} {artist}".strip()

    for country in regions:
        try:
            url = "https://itunes.apple.com/search"
            params = {
                "term": query,
                "entity": "song",
                "country": country,
                "limit": 10
            }
            resp = session.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for item in results:
                    track_name = item.get("trackName", "")
                    artist_name = item.get("artistName", "")
                    # 严格校验歌名和歌手匹配
                    title_match = title.lower() in track_name.lower() or track_name.lower() in title.lower()
                    artist_match = not artist or (artist.lower() in artist_name.lower() or artist_name.lower() in artist.lower())

                    if title_match and artist_match:
                        duration_ms = item.get("trackTimeMillis", 0)
                        duration_sec = int(duration_ms / 1000) if duration_ms else 0
                        artwork = item.get("artworkUrl100", "")
                        if artwork:
                            artwork = artwork.replace("100x100bb.jpg", "600x600bb.jpg").replace("100x100bb.png", "600x600bb.png")

                        release_date = item.get("releaseDate", "")
                        release_year = release_date[:4] if release_date else ""

                        return OfficialMetadata(
                            title=track_name,
                            artist=artist_name,
                            album=item.get("collectionName", ""),
                            duration_seconds=duration_sec,
                            cover_url=artwork,
                            release_year=release_year,
                            source=f"iTunes ({country})"
                        )
        except Exception:
            continue
    return None

def fetch_musicbrainz_metadata(title: str, artist: str) -> Optional[OfficialMetadata]:
    session = get_session()
    headers = {"User-Agent": "music-sync/1.0 ( contact@example.com )"}
    query = f'recording:"{title}" AND artist:"{artist}"'
    try:
        url = "https://musicbrainz.org/ws/2/recording/"
        params = {"query": query, "fmt": "json", "limit": 5}
        resp = session.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            recordings = data.get("recordings", [])
            for rec in recordings:
                length_ms = rec.get("length", 0)
                duration_sec = int(length_ms / 1000) if length_ms else 0
                releases = rec.get("releases", [])
                album = releases[0].get("title", "") if releases else ""
                release_date = releases[0].get("date", "") if releases else ""
                release_year = release_date[:4] if release_date else ""

                artist_credit = rec.get("artist-credit", [])
                artist_name = artist_credit[0].get("name", artist) if artist_credit else artist

                if duration_sec > 0:
                    return OfficialMetadata(
                        title=rec.get("title", title),
                        artist=artist_name,
                        album=album,
                        duration_seconds=duration_sec,
                        release_year=release_year,
                        source="MusicBrainz"
                    )
    except Exception:
        pass
    return None

def fetch_netease_metadata(title: str, artist: str) -> Optional[OfficialMetadata]:
    session = get_session()
    query = f"{title} {artist}".strip()
    try:
        url = "https://music.163.com/api/search/get/web"
        params = {"s": query, "type": 1, "limit": 5, "offset": 0}
        resp = session.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            songs = data.get("result", {}).get("songs", [])
            for song in songs:
                song_name = song.get("name", "")
                artists = song.get("artists", song.get("ar", []))
                artist_name = "/".join(a.get("name", "") for a in artists) if artists else ""
                # 校验歌名/歌手，避免模糊搜索第一条命中无关歌曲而污染基准元数据
                if not validate_candidate_match(song_name, artist_name, title, artist):
                    continue

                duration_ms = song.get("dt", song.get("duration", 0))
                duration_sec = int(duration_ms / 1000) if duration_ms else 0
                album_info = song.get("album", song.get("al", {}))
                album = album_info.get("name", "")
                cover = album_info.get("picUrl", "")

                return OfficialMetadata(
                    title=song_name,
                    artist=artist_name or artist,
                    album=album,
                    duration_seconds=duration_sec,
                    cover_url=cover,
                    source="NetEase"
                )
    except Exception:
        pass
    return None

def get_official_metadata(title: str, artist: str) -> OfficialMetadata:
    meta = fetch_itunes_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        return meta

    meta = fetch_musicbrainz_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        if not meta.cover_url:
            ne_meta = fetch_netease_metadata(title, artist)
            if ne_meta and ne_meta.cover_url:
                meta.cover_url = ne_meta.cover_url
        return meta

    meta = fetch_netease_metadata(title, artist)
    if meta and meta.duration_seconds > 0:
        return meta

    return OfficialMetadata(
        title=title,
        artist=artist,
        album="",
        duration_seconds=0,
        source="Fallback"
    )
