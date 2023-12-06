from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Crop(BaseModel):
    start: int
    end: int


class Stats(BaseModel):
    plays: int = 0
    last_played: Optional[datetime] = None


class Sound(BaseModel):
    filename: str
    original_filename: str

    source: Optional[str] = None
    source_title: Optional[str] = None

    created: datetime
    modified: datetime

    discord: Stats = Field(default_factory=lambda: Stats())
    twitch: Stats = Field(default_factory=lambda: Stats())

    crop: Optional[Crop] = None


class SoundOut(Sound):
    """
    Used for including the name of the sound in the JSON response.
    """

    name: str
