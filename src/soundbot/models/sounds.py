from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


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
    metadata: Optional[str] = "metadata.json"  # yt-dlp info JSON (None for uploaded files)
    subtitles: Optional[str] = None  # Subtitles file if available


class Sound(BaseModel):
    # Directory name for this sound (under sounds_folder)
    directory: str

    # File paths within the directory
    files: SoundFiles

    # Source information
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_duration: Optional[float] = None  # Original duration in seconds

    # Trim settings
    timestamps: Timestamps = Field(default_factory=Timestamps)

    # Audio settings - volume adjustment in "notches" (each notch = 3dB)
    # 0 = normal, negative = quieter, positive = louder
    # Range: -5 to +3 (reasonable limits)
    volume_adjust: int = 0

    @model_validator(mode="before")
    @classmethod
    def migrate_volume_field(cls, data: Any) -> Any:
        """Handle migration from old 'volume' float field to 'volume_adjust' int."""
        if isinstance(data, dict):
            # Remove old 'volume' field if present (was always 1.0, unused)
            data.pop("volume", None)
        return data

    @property
    def volume_db(self) -> float:
        """Convert notches to dB adjustment."""
        return self.volume_adjust * 3.0

    @property
    def volume_display(self) -> str:
        """Human-readable volume description."""
        if self.volume_adjust == 0:
            return "normal"
        elif self.volume_adjust < 0:
            return f"{self.volume_adjust} (quieter)"
        else:
            return f"+{self.volume_adjust} (louder)"

    # Metadata
    created: datetime = Field(default_factory=datetime.now)
    modified: datetime = Field(default_factory=datetime.now)
    added_by: Optional[str] = None  # Username of who added this sound

    # Usage statistics per platform
    discord: Stats = Field(default_factory=Stats)
    twitch: Stats = Field(default_factory=Stats)


class SoundOut(Sound):
    """Used for including the name of the sound in the JSON response."""

    name: str
