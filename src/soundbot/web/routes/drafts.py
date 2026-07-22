"""Draft workflow: download once, preview/trim, then commit as a real sound.

Drafts live in `sounds/.drafts/<draft_id>/` — inside the host-mounted sounds
volume so they survive restarts, but never publicly served (the /sounds
static mount rejects dot-directories and video files; see web.py).
"""

import json
import logging
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sound_service
from soundbot.services.ytdlp import ytdlp_service
from soundbot.web.dependencies import AdminUser, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/drafts", dependencies=[Depends(require_admin)])

DRAFTS_DIRNAME = ".drafts"
DRAFT_INFO_FILENAME = "draft.json"
DRAFT_MAX_AGE_SECONDS = 24 * 60 * 60  # GC drafts older than 24h


class DraftInfo(BaseModel):
    """Persisted draft metadata (draft.json) so drafts survive restarts."""

    url: str
    title: Optional[str] = None
    duration: Optional[float] = None
    created: datetime
    original_filename: str
    has_video: bool = False


def _drafts_root() -> Path:
    return sound_service.sounds_dir / DRAFTS_DIRNAME


def _validate_draft_id(draft_id: str) -> str:
    """Reject anything that isn't a uuid4 hex string (no path traversal)."""
    try:
        parsed = uuid.UUID(hex=draft_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Draft not found")
    # uuid.UUID accepts dashed/braced forms too; require the exact hex form
    # we generate so the id maps 1:1 onto the directory name.
    if parsed.hex != draft_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft_id


def _draft_dir(draft_id: str) -> Path:
    return _drafts_root() / _validate_draft_id(draft_id)


def _load_draft_info(draft_dir: Path) -> Optional[DraftInfo]:
    info_path = draft_dir / DRAFT_INFO_FILENAME
    if not info_path.exists():
        return None
    try:
        return DraftInfo.model_validate(json.loads(info_path.read_text()))
    except Exception as e:
        logger.warning(f"Unreadable draft.json in {draft_dir}: {e}")
        return None


def gc_old_drafts() -> None:
    """Delete draft dirs older than 24h (by draft.json created, else mtime)."""
    root = _drafts_root()
    if not root.is_dir():
        return
    now = time.time()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        age: float
        info = _load_draft_info(entry)
        if info is not None:
            age = now - info.created.timestamp()
        else:
            try:
                age = now - entry.stat().st_mtime
            except OSError:
                continue
        if age > DRAFT_MAX_AGE_SECONDS:
            logger.info(f"GC: removing stale draft {entry.name}")
            shutil.rmtree(entry, ignore_errors=True)


class CreateDraftBody(BaseModel):
    url: str


class CommitDraftBody(BaseModel):
    name: str
    start: Optional[float] = None
    end: Optional[float] = None


@router.post("")
async def create_draft(body: CreateDraftBody):
    """Download a URL into a draft dir and prepare a waveform preview.

    Slow (yt-dlp download + transcode, 30-90s) — handled inline like the
    other admin add/waveform endpoints.
    """
    gc_old_drafts()

    draft_id = uuid.uuid4().hex
    draft_dir = _drafts_root() / draft_id
    draft_dir.mkdir(parents=True, exist_ok=True)

    try:
        download = await ytdlp_service.download(body.url, draft_dir, "draft")
        if not download.success or download.original_file is None:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download: {download.error or 'unknown error'}",
            )

        original_file = download.original_file

        probe = await ffmpeg_service.probe(original_file)
        if not probe or not probe.has_audio:
            raise HTTPException(
                status_code=400, detail="Downloaded file has no audio"
            )

        waveform_path = draft_dir / "draft_waveform.mp3"
        waveform = await ffmpeg_service.extract_preview_audio(
            original_file, waveform_path
        )
        if not waveform.success:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to generate waveform audio: {waveform.error}",
            )

        duration = download.duration or probe.duration
        if duration is None:
            raise HTTPException(
                status_code=400, detail="Could not determine media duration"
            )

        info = DraftInfo(
            # Prefer yt-dlp's canonical URL (strips ?si= share/tracking params).
            url=download.canonical_url or body.url,
            title=download.title,
            duration=duration,
            created=datetime.now(),
            original_filename=original_file.name,
            has_video=probe.has_video,
        )
        _ = (draft_dir / DRAFT_INFO_FILENAME).write_text(info.model_dump_json(indent=2))
    except Exception:
        # Clean up the dir on ANY failure (download error, probe, transcode)
        shutil.rmtree(draft_dir, ignore_errors=True)
        raise

    return {
        "draft_id": draft_id,
        "duration": duration,
        "source_title": download.title,
        "source_url": info.url,
        "has_video": probe.has_video,
        "audio_url": f"/api/admin/drafts/{draft_id}/waveform-audio",
    }


@router.get("/{draft_id}/waveform-audio")
async def get_draft_waveform_audio(draft_id: str):
    """Serve the draft's waveform preview mp3 (admin only)."""
    draft_dir = _draft_dir(draft_id)
    waveform_path = draft_dir / "draft_waveform.mp3"
    if not waveform_path.exists():
        raise HTTPException(status_code=404, detail="Draft not found")

    return FileResponse(
        waveform_path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{draft_id}/commit")
async def commit_draft(body: CommitDraftBody, draft_id: str, user: AdminUser = Depends(require_admin)):
    """Create a real sound from the already-downloaded draft media."""
    gc_old_drafts()

    draft_dir = _draft_dir(draft_id)
    info = _load_draft_info(draft_dir)
    if info is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    source_path = draft_dir / info.original_filename
    if not source_path.exists():
        raise HTTPException(
            status_code=404, detail="Draft media file is missing"
        )

    result = await sound_service.add_sound_from_local_file(
        name=body.name,
        source_path=source_path,
        original_filename=info.original_filename,
        source_url=info.url,
        source_title=info.title,
        start=body.start,
        end=body.end,
        added_by=user.username,
    )
    if not result.success:
        lowered = result.message.lower()
        status = 409 if "already" in lowered else 400
        raise HTTPException(status_code=status, detail=result.message)

    # Copy succeeded and the sound exists — the draft is no longer needed.
    shutil.rmtree(draft_dir, ignore_errors=True)

    return {"name": body.name.lower()}


@router.delete("/{draft_id}", status_code=204)
async def delete_draft(draft_id: str) -> Response:
    """Delete a draft (idempotent — 204 even if already gone)."""
    draft_dir = _draft_dir(draft_id)
    if draft_dir.exists():
        shutil.rmtree(draft_dir, ignore_errors=True)
    return Response(status_code=204)
