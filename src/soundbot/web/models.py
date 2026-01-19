from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SoundResponse(BaseModel):
    """Sound data for the frontend API."""

    name: str
    # Audio file path relative to /sounds/
    audio_path: str
    # Source information
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_duration: Optional[float] = None  # Original duration in seconds
    # Trim settings
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None
    # Audio settings - volume adjustment in notches (0 = normal)
    volume_adjust: int = 0
    # Metadata
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    # Play counts
    discord_plays: int = 0
    twitch_plays: int = 0


class SoundsResponse(BaseModel):
    """Response for /api/sounds endpoint."""

    sounds: List[SoundResponse]
    total: int
