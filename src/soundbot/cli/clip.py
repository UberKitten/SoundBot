"""Create a sound by clipping a local video file."""

from pathlib import Path
from typing import Optional

from soundbot.models.sounds import sanitize_name
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sound_service


def parse_timestamp(value: str) -> float:
    """Parse HH:MM:SS, MM:SS, SS, or seconds (with optional .fractional) to float seconds."""
    value = value.strip()
    if ":" not in value:
        return float(value)
    parts = value.split(":")
    if len(parts) > 3:
        raise ValueError(f"Too many colons in timestamp: {value!r}")
    # right-align so MM:SS and HH:MM:SS both work
    secs = 0.0
    for i, part in enumerate(reversed(parts)):
        secs += float(part) * (60**i)
    return secs


async def clip_video(
    video: str,
    start: str,
    end: str,
    name: Optional[str] = None,
    volume_adjust: int = 0,
    overwrite: bool = False,
) -> int:
    """Clip a video file into a sound. Returns process exit code."""
    video_path = Path(video).expanduser()
    if not video_path.exists():
        print(f"❌ Video file not found: {video_path}")
        return 1

    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end)
    if end_s <= start_s:
        print(f"❌ End ({end}) must be after start ({start})")
        return 1

    # Resolve default name from source title if not provided
    if name is None:
        probe = await ffmpeg_service.probe(video_path)
        if probe and probe.title:
            name = probe.title
            print(f"📛 Using source title as name: {name}")
        else:
            name = video_path.stem
            print(f"📛 No title in metadata, using filename: {name}")

    if not sanitize_name(name):
        print(f"❌ Name '{name}' has no usable characters after sanitization")
        return 1

    print(f"🎬 Clipping {start_s:.3f}s → {end_s:.3f}s ({end_s - start_s:.3f}s)")

    result = await sound_service.add_sound_from_video_path(
        name=name,
        video_path=video_path,
        start=start_s,
        end=end_s,
        volume_adjust=volume_adjust,
        overwrite=overwrite,
    )

    if result.success:
        print(f"✅ {result.message}")
        if result.timings:
            print(f"⏱  {result.timing_summary()}")
        return 0
    else:
        print(f"❌ {result.message}")
        if result.timings:
            print(f"⏱  {result.timing_summary()}")
        return 1
