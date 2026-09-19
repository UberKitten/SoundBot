import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from soundbot.services.ffmpeg import FFmpegService

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _run(command: list[str | Path]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(argument) for argument in command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result


def _has_svt_av1_encoder() -> bool:
    if FFMPEG is None:
        return False
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-h", "encoder=libsvtav1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return "Encoder libsvtav1" in result.stdout + result.stderr


def _probe_streams(path: Path) -> list[dict[str, Any]]:
    assert FFPROBE is not None
    result = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            (
                "stream=codec_type,codec_name,profile,pix_fmt,width,height,"
                "r_frame_rate,time_base,color_space,color_transfer,color_primaries,"
                "sample_rate,channels"
            ),
            "-of",
            "json",
            path,
        ]
    )
    return json.loads(result.stdout)["streams"]


def _make_live_shaped_source(path: Path) -> None:
    assert FFMPEG is not None
    _run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=0.5",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            "0.5",
            "-c:v",
            "libsvtav1",
            "-preset",
            "11",
            "-pix_fmt",
            "yuv420p10le",
            "-bsf:v",
            (
                "av1_metadata=color_primaries=9:transfer_characteristics=18:"
                "matrix_coefficients=9"
            ),
            "-c:a",
            "libopus",
            "-shortest",
            path,
        ]
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None or not _has_svt_av1_encoder(),
    reason="real 10-bit AV1 regression requires ffmpeg, ffprobe, and libsvtav1",
)
async def test_browser_video_downconverts_ten_bit_av1_for_browser_playback(
    tmp_path: Path,
) -> None:
    assert FFMPEG is not None
    source = tmp_path / "live-shaped-source.mkv"
    old_output = tmp_path / "old-high10.mp4"
    fixed_output = tmp_path / "fixed-main.mp4"
    _make_live_shaped_source(source)

    source_video = next(
        stream for stream in _probe_streams(source) if stream["codec_type"] == "video"
    )
    assert source_video == {
        "codec_name": "av1",
        "profile": "Main",
        "codec_type": "video",
        "width": 1280,
        "height": 720,
        "pix_fmt": "yuv420p10le",
        "color_space": "bt2020nc",
        "color_transfer": "arib-std-b67",
        "color_primaries": "bt2020",
        "r_frame_rate": "30/1",
        "time_base": "1/1000",
    }

    # Reproduce the old transcode shape: libx264 inherits the source's 10-bit
    # pixel format and creates the H.264 High 10 file rejected by web players.
    _run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            old_output,
        ]
    )
    old_video = next(
        stream
        for stream in _probe_streams(old_output)
        if stream["codec_type"] == "video"
    )
    assert old_video["codec_name"] == "h264"
    assert old_video["profile"] == "High 10"
    assert old_video["pix_fmt"] == "yuv420p10le"

    result = await FFmpegService().make_browser_video(source, fixed_output)

    assert result.success, result.error
    assert result.remuxed is False
    streams = _probe_streams(fixed_output)
    fixed_video = next(
        stream for stream in streams if stream["codec_type"] == "video"
    )
    fixed_audio = next(
        stream for stream in streams if stream["codec_type"] == "audio"
    )
    assert {
        key: fixed_video[key]
        for key in ("codec_name", "profile", "width", "height", "pix_fmt")
    } == {
        "codec_name": "h264",
        "profile": "Main",
        "width": 1280,
        "height": 720,
        "pix_fmt": "yuv420p",
    }
    assert {
        key: fixed_audio[key]
        for key in ("codec_name", "profile", "sample_rate", "channels")
    } == {
        "codec_name": "aac",
        "profile": "LC",
        "sample_rate": "48000",
        "channels": 2,
    }
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-i",
            fixed_output,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ]
    )
