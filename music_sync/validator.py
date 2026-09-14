import os
from typing import List, Tuple
from mutagen import File
from music_sync.config import load_config

def is_artist_match(candidate_artist: str, target_artist: str) -> bool:
    if not target_artist:
        return True
    c_art = candidate_artist.lower().replace(" ", "").replace("、", "/").replace("&", "/")
    t_art = target_artist.lower().replace(" ", "")
    for a in c_art.split("/"):
        if t_art in a or a in t_art:
            return True
    return False

def is_title_match(candidate_title: str, target_title: str) -> bool:
    if not target_title:
        return True
    c_title = candidate_title.lower().replace(" ", "")
    t_title = target_title.lower().replace(" ", "")
    return t_title in c_title or c_title in t_title

def validate_candidate_match(candidate_title: str, candidate_artist: str, target_title: str, target_artist: str) -> bool:
    if not is_title_match(candidate_title, target_title):
        return False
    if target_artist and not is_artist_match(candidate_artist, target_artist):
        return False
    return True

def check_blacklist(text: str, custom_keywords: List[str] = None) -> Tuple[bool, str]:
    if not text:
        return False, ""
    cfg = load_config()
    keywords = custom_keywords or cfg.blacklist_keywords
    text_lower = text.lower()
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        if kw_clean in text_lower:
            return True, kw
    return False, ""

def validate_duration(candidate_duration: int, target_duration: int, tolerance: int = None) -> bool:
    if target_duration <= 0 or candidate_duration <= 0:
        return True
    if tolerance is None:
        tolerance = load_config().tolerance_seconds
    return abs(candidate_duration - target_duration) <= tolerance

def validate_audio_file(file_path: str, target_duration: int, tolerance: int = None) -> Tuple[bool, float, str]:
    if not os.path.exists(file_path):
        return False, 0.0, "文件不存在"
    try:
        audio = File(file_path)
        if audio is None or audio.info is None:
            return False, 0.0, "无法解析音频格式"
        actual_duration = audio.info.length
        if target_duration > 0:
            if tolerance is None:
                tolerance = load_config().tolerance_seconds
            if abs(actual_duration - target_duration) > tolerance:
                return False, actual_duration, f"实测时长 {actual_duration:.1f}s 与基准时长 {target_duration}s 差异超出容差 (±{tolerance}s)"
        return True, actual_duration, "OK"
    except Exception as e:
        return False, 0.0, f"校验出错: {e}"
