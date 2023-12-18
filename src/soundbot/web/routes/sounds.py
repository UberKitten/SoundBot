import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Response
from ffmpeg import FFmpeg

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.web.dependencies import no_cache

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/sounds", dependencies=[Depends(no_cache)])
async def get_sounds():
    return state.sounds


@router.get("/api/sounds/{sound_name}", dependencies=[Depends(no_cache)])
async def get_sound_info(sound_name: str):
    sound = state.sounds[sound_name]

    path = Path(settings.sounds_folder).joinpath(sound.filename)

    ffprobe = FFmpeg(executable="ffprobe").input(
        url=path,
        print_format="json",
        show_format=None,
    )
    return Response(content=ffprobe.execute(), media_type="application/json")
