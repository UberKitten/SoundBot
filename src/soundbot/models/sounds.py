from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Timestamps(BaseModel):
    """Start and end times for trimming, in seconds."""

    start: Optional[float] = None
    end: Optional[float] = None


class Stats(BaseModel):
    plays: int = 0
    last_played: Optional[datetime] = None


class SoundFiles(BaseModel):
    """Paths to sound files, relative to the sound's directory."""

    original: str  # Original downloaded file (video or audio)
    trimmed_video: Optional[str] = None  # Trimmed video file (if source was video)
    trimmed_audio: str  # Trimmed and normalized audio for Discord playback
    metadata: str = "metadata.json"  # yt-dlp info JSON
    subtitles: Optional[str] = None  # Subtitles file if available


class Sound(BaseModel):
    # Directory name for this sound (under sounds_folder)
    # If None, this is a legacy sound stored as a flat file
    directory: Optional[str] = None

    # File paths within the directory (new format)
    files: Optional[SoundFiles] = None

    # Legacy format: filename directly in sounds_folder
    filename: Optional[str] = None
    original_filename: Optional[str] = None

    # Source information
    source_url: Optional[str] = None
    source: Optional[str] = None  # Legacy alias for source_url
    source_title: Optional[str] = None
    source_duration: Optional[float] = None  # Original duration in seconds

    # Trim settings
    timestamps: Timestamps = Field(default_factory=Timestamps)
    crop: Optional[dict] = None  # Legacy crop field

    # Audio settings
    volume: float = (
        1.0  # Volume multiplier (1.0 = normalized, 0.5 = half, 2.0 = double)
    )

    # Metadata
    created: datetime = Field(default_factory=datetime.now)
    modified: datetime = Field(default_factory=datetime.now)
    added_by: Optional[str] = None  # Username of who added this sound

    # Usage statistics per platform
    discord: Stats = Field(default_factory=Stats)
    twitch: Stats = Field(default_factory=Stats)

    @property
    def is_legacy(self) -> bool:
        """Check if this is a legacy sound (flat file structure)."""
        return self.directory is None and self.filename is not None


class SoundOut(Sound):
    """Used for including the name of the sound in the JSON response."""

    name: str


# Legacy model for migration
class LegacySound(BaseModel):
    filename: str
    original_filename: str
    source: Optional[str] = None
    source_title: Optional[str] = None
    created: datetime
    modified: datetime
    discord: Stats = Field(default_factory=Stats)
    twitch: Stats = Field(default_factory=Stats)


class LegacyCrop(BaseModel):
    start: int
    end: int
