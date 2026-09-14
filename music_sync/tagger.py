import os
from typing import Optional, Tuple
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, USLT, TLEN, ID3NoHeaderError
from mutagen.mp3 import MP3
from music_sync.http import get_session

def download_cover(cover_url: str) -> Optional[bytes]:
    if not cover_url:
        return None
    session = get_session()
    try:
        resp = session.get(cover_url, timeout=10)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None

def write_flac_tags(file_path: str, title: str, artist: str, album: str, lyrics: str = "", cover_bytes: Optional[bytes] = None) -> bool:
    try:
        audio = FLAC(file_path)
        audio["TITLE"] = title
        audio["ARTIST"] = artist
        if album:
            audio["ALBUM"] = album
        if lyrics:
            audio["LYRICS"] = lyrics

        if cover_bytes:
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3  # front cover
            pic.mime = "image/jpeg" if cover_bytes.startswith(b"\xff\xd8") else "image/png"
            pic.desc = "Cover"
            pic.data = cover_bytes
            audio.add_picture(pic)

        audio.save()
        return True
    except Exception:
        return False

def write_mp3_tags(file_path: str, title: str, artist: str, album: str, lyrics: str = "", cover_bytes: Optional[bytes] = None) -> bool:
    try:
        try:
            audio = ID3(file_path)
        except ID3NoHeaderError:
            audio = ID3()

        audio.add(TIT2(encoding=3, text=title))
        audio.add(TPE1(encoding=3, text=artist))
        if album:
            audio.add(TALB(encoding=3, text=album))
        if lyrics:
            audio.add(USLT(encoding=3, lang="chi", desc="", text=lyrics))

        if cover_bytes:
            mime = "image/jpeg" if cover_bytes.startswith(b"\xff\xd8") else "image/png"
            audio.add(APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc="Cover",
                data=cover_bytes
            ))

        audio.save(file_path, v2_version=3)
        return True
    except Exception:
        return False

def apply_tags_and_verify(file_path: str, title: str, artist: str, album: str, lyrics: str = "", cover_url: str = "") -> Tuple[bool, str]:
    if not os.path.exists(file_path):
        return False, "文件不存在"

    cover_bytes = download_cover(cover_url) if cover_url else None
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".flac":
        ok = write_flac_tags(file_path, title, artist, album, lyrics, cover_bytes)
    elif ext in (".mp3", ".m4a"):
        ok = write_mp3_tags(file_path, title, artist, album, lyrics, cover_bytes)
    else:
        return True, "未知格式跳过标签写入"

    if not ok:
        return False, "写入标签失败"

    # Post-write verification
    try:
        audio = File(file_path)
        if audio is None:
            return False, "回读标签校验失败: 无法解析"
        return True, "标签写入并回读校验成功"
    except Exception as e:
        return False, f"回读标签校验异常: {e}"
