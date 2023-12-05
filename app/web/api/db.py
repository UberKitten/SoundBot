import json
import logging
import pathlib
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.core.settings import settings
from app.web.dependencies import no_cache
from app.web.models import DB, Sound

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/db.json", dependencies=[Depends(no_cache)])
async def db():
    sound_path = pathlib.Path(settings.sounds_root)

    with open("mount/db.json") as db_file:
        db_json: Dict[str, Any] = json.load(db_file)

    db = DB.parse_obj(db_json)

    # Add in sounds that aren't in the existing db
    sound_names = [sound.name for sound in db.sounds]

    for sound_path_file in sound_path.glob("*"):
        if sound_path_file.is_file() and sound_path_file.stem not in sound_names:
            db.sounds.append(Sound(name=sound_path_file.stem))

    # Fill in file info for each sound
    for sound in db.sounds:
        sound_files = list(sound_path.glob(f"{sound.name}.*"))
        if len(sound_files) > 0:
            best_match_file = next(
                (file for file in sound_files if file.suffix == ".mp3"), sound_files[0]
            )

            sound.filename = best_match_file.name
            sound.modified = best_match_file.stat().st_mtime_ns

    return db
