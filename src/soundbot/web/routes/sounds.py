import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from soundbot.core.state import state
from soundbot.services.sounds import sound_service
from soundbot.web.dependencies import no_cache
from soundbot.web.models import SoundResponse, SoundsResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/api/v2/sounds", dependencies=[Depends(no_cache)], response_model=SoundsResponse
)
async def get_sounds_v2():
    """Get all sounds with full metadata."""
    sounds: list[SoundResponse] = []

    for name, sound in state.sounds.items():
        # Determine the audio path for the frontend
        audio_path = None
        if sound.is_legacy and sound.filename:
            audio_path = sound.filename
        elif sound.directory and sound.files:
            audio_path = f"{sound.directory}/{sound.files.trimmed_audio}"

        sounds.append(
            SoundResponse(
                name=name,
                audio_path=audio_path,
                source_url=sound.source_url or sound.source,
                source_title=sound.source_title,
                source_duration=sound.source_duration,
                trim_start=sound.timestamps.start,
                trim_end=sound.timestamps.end,
                volume=sound.volume,
                created=sound.created,
                modified=sound.modified,
                discord_plays=sound.discord.plays,
                twitch_plays=sound.twitch.plays,
                is_legacy=sound.is_legacy,
            )
        )

    return SoundsResponse(sounds=sounds, total=len(sounds))


@router.get("/api/sounds", dependencies=[Depends(no_cache)])
async def get_sounds():
    """Get all sounds (legacy format - returns raw state)."""
    return state.sounds


@router.get("/api/sounds/{sound_name}", dependencies=[Depends(no_cache)])
async def get_sound_info(sound_name: str):
    """Get information about a specific sound."""
    sound = sound_service.get_sound(sound_name)
    if not sound:
        raise HTTPException(status_code=404, detail="Sound not found")

    return {
        "name": sound_name,
        "sound": sound.model_dump(),
    }


@router.get("/api/sounds/{sound_name}/audio")
async def get_sound_audio(sound_name: str):
    """Get the audio file for a sound."""
    audio_path = sound_service.get_audio_path(sound_name)
    if not audio_path or not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")

    return Response(
        content=audio_path.read_bytes(),
        media_type="audio/ogg",
        headers={"Content-Disposition": f'inline; filename="{sound_name}.ogg"'},
    )


@router.get("/api/search", dependencies=[Depends(no_cache)])
async def search_sounds(q: Optional[str] = None):
    """Search sounds by name."""
    if not q:
        return {"results": list(state.sounds.keys())}

    results = sound_service.search_sounds(q)
    return {"results": [name for name, _ in results]}
