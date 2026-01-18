from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


# New API models
class SoundResponse(BaseModel):
    """Sound data for the frontend API."""

    name: str
    # Audio file path relative to /sounds/
    audio_path: Optional[str] = None
    # Source information
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_duration: Optional[float] = None  # Original duration in seconds
    # Trim settings
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None
    # Audio settings
    volume: float = 1.0
    # Metadata
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    # Play counts
    discord_plays: int = 0
    twitch_plays: int = 0
    # Flags
    is_legacy: bool = False


class SoundsResponse(BaseModel):
    """Response for /api/v2/sounds endpoint."""

    sounds: List[SoundResponse]
    total: int


# Legacy API models (for backward compatibility)
class OldSound(BaseModel):
    name: str
    filename: Optional[str] = None
    modified: Optional[int] = None
    count: int = 0
    tags: List[str] = []


class OldDB(BaseModel):
    entrances: Dict[str, str]
    exits: Dict[str, str]
    sounds: List[OldSound]
    ignoreList: List[str]
