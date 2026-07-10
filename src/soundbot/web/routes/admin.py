import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import OperationResult, sound_service
from soundbot.web.dependencies import AdminUser, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _fail(result: OperationResult) -> HTTPException:
    """Map an OperationResult failure to an HTTPException with a JSON detail."""
    msg = result.message
    lowered = msg.lower()
    if "not found" in lowered:
        status = 404
    elif "already" in lowered:
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail=msg)


class AddSoundBody(BaseModel):
    name: str
    url: str
    start: Optional[float] = None
    end: Optional[float] = None
    volume_adjust: int = 0


class TrimBody(BaseModel):
    start: Optional[float] = None
    end: Optional[float] = None
    volume_adjust: Optional[int] = None


class PatchBody(BaseModel):
    new_name: Optional[str] = None
    volume_adjust: Optional[int] = None


@router.post("/sounds")
async def add_sound(body: AddSoundBody, user: AdminUser = Depends(require_admin)):
    """Add a new sound from a URL (may take 30s+ for yt-dlp)."""
    result = await sound_service.add_sound(
        name=body.name,
        url=body.url,
        start=body.start,
        end=body.end,
        volume_adjust=body.volume_adjust,
        added_by=user.username,
    )
    if not result.success:
        raise _fail(result)
    return {"name": body.name.lower()}


@router.get("/sounds/{name}/waveform")
async def get_waveform(name: str):
    """Ensure a full-length browser-decodable preview of the original exists."""
    sound = sound_service.get_sound(name)
    if not sound:
        raise HTTPException(status_code=404, detail=f"Sound '{name}' not found")

    sound_dir = sound_service.sounds_dir / sound.directory
    # files.original may be a bare filename or an absolute path (external clips);
    # pathlib's / preserves an absolute RHS, so this resolves correctly either way.
    original_path = sound_dir / sound.files.original
    if not original_path.exists():
        raise HTTPException(
            status_code=409,
            detail="Original file is missing; the sound may need to be re-downloaded.",
        )

    waveform_path = sound_dir / f"{sound.directory}_waveform.mp3"

    # Regenerate if missing or stale (older than the original — covers redownload).
    needs_generate = True
    if waveform_path.exists():
        try:
            needs_generate = (
                waveform_path.stat().st_mtime < original_path.stat().st_mtime
            )
        except OSError:
            needs_generate = True

    if needs_generate:
        result = await ffmpeg_service.extract_preview_audio(
            original_path, waveform_path
        )
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate waveform audio: {result.error}",
            )

    duration = sound.source_duration
    if duration is None:
        duration = await ffmpeg_service.get_duration(original_path)

    try:
        version = int(waveform_path.stat().st_mtime)
    except OSError:
        version = 0

    audio_url = f"/sounds/{sound.directory}/{waveform_path.name}?v={version}"

    return {
        "audio_url": audio_url,
        "duration": duration,
        "start": sound.timestamps.start,
        "end": sound.timestamps.end,
        "volume_adjust": sound.volume_adjust,
        "source_title": sound.source_title,
        "source_url": sound.source_url,
    }


def _needs_regenerate(output: Path, source: Path) -> bool:
    """True if output is missing or older than the source (covers re-trim)."""
    if not output.exists():
        return True
    try:
        return output.stat().st_mtime < source.stat().st_mtime
    except OSError:
        return True


@router.get("/sounds/{name}/video")
async def get_clip_video(name: str):
    """Serve a browser-playable MP4 of the sound's clip (admin only).

    Transcodes on demand to {safe}_clip.mp4 in the sound dir; regenerated
    whenever the source (trimmed video, or original) is newer — e.g. after
    a re-trim rewrites {safe}_trimmed.mkv.
    """
    sound = sound_service.get_sound(name)
    if not sound:
        raise HTTPException(status_code=404, detail=f"Sound '{name}' not found")

    sound_dir = sound_service.sounds_dir / sound.directory

    # Prefer the already-trimmed video; fall back to the original (with the
    # trim applied during transcode) if it has a video stream.
    source_path: Optional[Path] = None
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None

    if sound.files.trimmed_video:
        candidate = sound_dir / sound.files.trimmed_video
        if candidate.exists():
            source_path = candidate

    if source_path is None:
        # files.original may be a bare filename or an absolute path
        # (external clips); pathlib's / preserves an absolute RHS.
        original_path = sound_dir / sound.files.original
        if original_path.exists():
            probe = await ffmpeg_service.probe(original_path)
            if probe and probe.has_video:
                source_path = original_path
                trim_start = sound.timestamps.start
                trim_end = sound.timestamps.end

    if source_path is None:
        raise HTTPException(status_code=409, detail="Sound has no video")

    clip_path = sound_dir / f"{sound.directory}_clip.mp4"

    if _needs_regenerate(clip_path, source_path):
        result = await ffmpeg_service.make_browser_video(
            source_path,
            clip_path,
            start=trim_start,
            end=trim_end,
        )
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to transcode clip video: {result.error}",
            )

    # FileResponse in starlette 0.50 handles Range requests natively (206 +
    # Content-Range) — required for iOS <video>. Auth-gated, so keep it out
    # of shared caches.
    return FileResponse(
        clip_path,
        media_type="video/mp4",
        headers={"Cache-Control": "private, no-store"},
    )


@router.put("/sounds/{name}/trim")
async def trim_sound(name: str, body: TrimBody):
    """Update trim timestamps (and optionally volume) with a single re-encode."""
    sound = sound_service.get_sound(name)
    if not sound:
        raise HTTPException(status_code=404, detail=f"Sound '{name}' not found")

    resolved = sound_service.resolve_sound_name(name)
    assert resolved is not None
    canonical = resolved[0]

    # If volume changed, mutate volume_adjust BEFORE edit_timestamps so the
    # single re-encode inside edit_timestamps (which reads sound.volume_db)
    # applies the new volume — avoids a second encode pass.
    if body.volume_adjust is not None:
        clamped = max(-5, min(3, body.volume_adjust))
        sound.volume_adjust = clamped

    result = await sound_service.edit_timestamps(
        canonical, start=body.start, end=body.end
    )
    if not result.success:
        raise _fail(result)

    return {
        "start": sound.timestamps.start,
        "end": sound.timestamps.end,
        "volume_adjust": sound.volume_adjust,
    }


@router.patch("/sounds/{name}")
async def patch_sound(name: str, body: PatchBody):
    """Rename and/or set the volume of a sound."""
    resolved = sound_service.resolve_sound_name(name)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Sound '{name}' not found")
    current = resolved[0]

    if body.volume_adjust is not None:
        vol_result = await sound_service.set_volume(current, body.volume_adjust)
        if not vol_result.success:
            raise _fail(vol_result)

    if body.new_name is not None and body.new_name.lower() != current:
        rename_result = await sound_service.rename_sound(current, body.new_name)
        if not rename_result.success:
            raise _fail(rename_result)
        current = body.new_name.lower()

    return {"name": current}


@router.delete("/sounds/{name}", status_code=204)
async def delete_sound(name: str) -> Response:
    """Delete a sound."""
    result = await sound_service.delete_sound(name)
    if not result.success:
        raise _fail(result)
    return Response(status_code=204)


@router.post("/sounds/{name}/redownload")
async def redownload_sound(name: str):
    """Re-download a sound from its original source URL."""
    result = await sound_service.redownload_sound(name)
    if not result.success:
        raise _fail(result)
    return {"ok": True}
