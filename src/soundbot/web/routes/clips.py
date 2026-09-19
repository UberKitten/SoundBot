"""Public signed clip links: GET /clips/{name}.mp4?exp=...&sig=...

No cookie/session auth — Discord's embed prober and OBS must be able to
hotlink these, so the HMAC signature (see web/clipsign.py) IS the auth.
The path ends in ".mp4" because Discord only inline-embeds direct links
whose path ends in the extension.
"""

import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from soundbot.core.state import state
from soundbot.models.sounds import Sound
from soundbot.services.clips import ClipError, ensure_clip
from soundbot.services.sounds import sound_service
from soundbot.web.clipsign import verify_clip_directory_sig, verify_clip_sig

logger = logging.getLogger(__name__)
router = APIRouter()

CLIP_SUFFIX = ".mp4"


# HEAD must be registered explicitly — FastAPI GET routes don't answer HEAD,
# and Discord's embed prober HEADs the link before embedding. FileResponse
# handles HEAD natively (headers only, no body).
@router.api_route("/clip-ids/{filename}", methods=["GET", "HEAD"])
async def get_public_clip_by_directory(
    filename: str, exp: int = 0, sig: str = ""
):
    """Serve a clip through its bounded storage identifier."""
    directory = _identifier_from_filename(filename)
    if not sig or not verify_clip_directory_sig(directory, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")
    _reject_expired(exp)

    sound = next(
        (candidate for candidate in state.sounds.values() if candidate.directory == directory),
        None,
    )
    if not sound:
        raise HTTPException(status_code=404, detail="Sound not found")
    return await _serve_clip(sound, directory)


@router.api_route("/clips/{filename:path}", methods=["GET", "HEAD"])
async def get_public_clip(filename: str, exp: int = 0, sig: str = ""):
    """Serve a legacy canonical-name clip URL."""
    name = _identifier_from_filename(filename).lower()
    if not sig or not verify_clip_sig(name, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")
    _reject_expired(exp)

    sound = state.sounds.get(name)
    if not sound:
        raise HTTPException(status_code=404, detail="Sound not found")
    return await _serve_clip(sound, name)


def _identifier_from_filename(filename: str) -> str:
    if not filename.endswith(CLIP_SUFFIX):
        raise HTTPException(status_code=404, detail="Not found")
    return filename[: -len(CLIP_SUFFIX)]


def _reject_expired(exp: int) -> None:
    if exp < int(time.time()):
        raise HTTPException(status_code=403, detail="Link expired")


async def _serve_clip(sound: Sound, log_identifier: str) -> FileResponse:
    # Lazy safety net — normally the clip already exists (eager generation
    # at mutation time + startup backfill), so this is just an mtime check.
    try:
        result = await ensure_clip(sound, sound_service.sounds_dir)
    except ClipError as e:
        logger.error(f"Clip generation failed for '{log_identifier}': {e}")
        raise HTTPException(status_code=500, detail="Clip generation failed")
    if result is None:
        raise HTTPException(status_code=404, detail="Sound has no video")

    # FileResponse (starlette 0.50) natively supports Range/206 + HEAD —
    # both required by Discord's embed prober and seekable <video>.
    return FileResponse(
        result.path,
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=86400"},
    )
