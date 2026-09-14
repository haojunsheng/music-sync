from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class TrackCandidate:
    source: str
    song_id: str
    title: str
    artist: str
    album: str
    duration_seconds: int
    quality: str  # flac, ape, 320k, 128k, 96k, aac, mp3
    file_ext: str  # flac, ape, mp3, m4a
    download_url: Optional[str] = None
    extra_data: Optional[dict] = None

class BaseSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def search_and_resolve(self, title: str, artist: str, target_duration: int = 0) -> List[TrackCandidate]:
        pass
