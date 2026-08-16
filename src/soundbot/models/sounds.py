import hashlib
import math
import re
from collections.abc import Collection
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


RandomMode = Literal["together", "separate"]


TRIM_TIME_ZERO_EPSILON = 1e-6


def sanitize_name(name: str) -> str:
    """Sanitize a sound name into the established persisted path form."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", "_", name)
    return name.lower().strip("_")[:50]


def allocate_sound_directory(name: str, used_directories: Collection[str]) -> str:
    """Allocate a deterministic collision-safe directory for a new sound."""
    base = sanitize_name(name)
    if not base:
        raise ValueError(f"'{name}' is not a valid sound name")
    used = set(used_directories)
    if base not in used:
        return base
    for nonce in range(1000):
        suffix = hashlib.sha256(f"{name.lower()}:{nonce}".encode()).hexdigest()[:10]
        candidate = f"{base[:39]}-{suffix}"
        if candidate not in used:
            return candidate
    raise ValueError(f"Could not allocate unique storage for sound '{name}'")


def canonicalize_trim_timestamp(value: Optional[float]) -> Optional[float]:
    """Collapse unrepresentable boundary noise while preserving real trim precision."""
    if value is None:
        return None
    if not math.isfinite(value):
        raise ValueError("Trim timestamps must be finite")
    if abs(value) <= TRIM_TIME_ZERO_EPSILON:
        return 0.0
    return value



def validate_playable_duration(value: float) -> float:
    """Require a finite, positive duration measured from the playable OGG."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Playable OGG duration must be finite and greater than zero")
    return value


class Timestamps(BaseModel):
    """Start and end times for trimming, in seconds."""

    start: Optional[float] = None
    end: Optional[float] = None

    @field_validator("start", "end")
    @classmethod
    def canonicalize_boundary(cls, value: Optional[float]) -> Optional[float]:
        return canonicalize_trim_timestamp(value)


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
    duration: float  # Final playable OGG duration in seconds

    # Trim settings
    timestamps: Timestamps = Field(default_factory=Timestamps)

    # Audio settings - volume adjustment in "notches" (each notch = 3dB)
    # 0 = normal, negative = quieter, positive = louder
    # Range: -5 to +3 (reasonable limits)
    volume_adjust: int = 0

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, value: float) -> float:
        return validate_playable_duration(value)

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

    # Alternate names for this sound
    aliases: list[str] = Field(default_factory=list)

    # Usage statistics per platform
    discord: Stats = Field(default_factory=Stats)
    twitch: Stats = Field(default_factory=Stats)
    web: Stats = Field(default_factory=Stats)
    # Clip shown in Discord chat but NOT played in a voice channel (nobody
    # was in voice). Mutually exclusive with `discord` plays per event.
    discord_clips: Stats = Field(default_factory=Stats)


class SoundGroupData(BaseModel):
    """Persistent data for a sound group."""

    members: list[str] = Field(default_factory=list)
    created: datetime = Field(default_factory=datetime.now)

    # How members enter /random. "together": the group occupies one slot and a
    # member is picked from it (so a 100-sound group doesn't dominate pulls).
    # "separate": each member competes individually like ungrouped sounds.
    random_mode: RandomMode = "together"

    # Usage statistics per platform
    discord: Stats = Field(default_factory=Stats)
    twitch: Stats = Field(default_factory=Stats)
    web: Stats = Field(default_factory=Stats)


class SoundOut(Sound):
    """Used for including the name of the sound in the JSON response."""

    name: str
