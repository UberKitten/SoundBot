import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from soundbot.models.sounds import Sound, SoundFiles
from soundbot.services.clips import ClipError, ensure_clip
from soundbot.services.ffmpeg import (
    FFmpegService,
    ProbeResult,
    ProcessResult,
    ffmpeg_service,
    is_browser_video_compatible,
)

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

def _has_x264_pixel_format(pixel_format: str) -> bool:
    if FFMPEG is None:
        return False
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-h", "encoder=libx264"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0 and pixel_format in result.stdout + result.stderr


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

def _make_h264_source(path: Path, *, ten_bit: bool = False) -> None:
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
            "testsrc2=size=320x180:rate=24:duration=0.5",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            "0.5",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p10le" if ten_bit else "yuv420p",
            "-profile:v",
            "high10" if ten_bit else "main",
            "-c:a",
            "aac",
            "-profile:a",
            "aac_low",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            path,
        ]
    )


def _assert_main_browser_output(path: Path) -> None:
    streams = _probe_streams(path)
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next(stream for stream in streams if stream["codec_type"] == "audio")
    assert {
        key: video[key]
        for key in ("codec_name", "profile", "width", "pix_fmt")
    } == {
        "codec_name": "h264",
        "profile": "Main",
        "width": 320,
        "pix_fmt": "yuv420p",
    }
    assert {
        key: audio[key]
        for key in ("codec_name", "profile", "sample_rate", "channels")
    } == {
        "codec_name": "aac",
        "profile": "LC",
        "sample_rate": "48000",
        "channels": 2,
    }


def _sound_for_video(directory: str, filename: str) -> Sound:
    return Sound(
        directory=directory,
        files=SoundFiles(
            original=filename,
            trimmed_video=filename,
            trimmed_audio=f"{directory}.ogg",
        ),
        duration=0.5,
    )


def _make_newer(path: Path, source: Path) -> None:
    timestamp = source.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(timestamp, timestamp))


def test_browser_compatibility_requires_narrow_output_contract() -> None:
    compatible = ProbeResult(
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        has_video=True,
        video_codec="h264",
        video_profile="Main",
        video_pixel_format="yuv420p",
        width=1280,
        has_audio=True,
        audio_codec="aac",
        audio_profile="LC",
        sample_rate=48000,
        channels=2,
    )

    assert is_browser_video_compatible(compatible, require_audio=True)
    assert not is_browser_video_compatible(
        compatible.model_copy(update={"audio_profile": "HE-AAC"}),
        require_audio=True,
    )
    assert is_browser_video_compatible(
        compatible.model_copy(update={"sample_rate": 44100}),
        require_audio=True,
    )
    assert is_browser_video_compatible(
        compatible.model_copy(update={"channels": 6}),
        require_audio=True,
    )
    assert not is_browser_video_compatible(
        compatible.model_copy(update={"sample_rate": 32000}),
        require_audio=True,
    )
    assert not is_browser_video_compatible(
        compatible.model_copy(update={"channels": 7}),
        require_audio=True,
    )
    assert not is_browser_video_compatible(
        compatible.model_copy(update={"audio_codec": "opus"}),
        require_audio=True,
    )
    assert not is_browser_video_compatible(
        compatible.model_copy(update={"format_name": "matroska,webm"}),
        require_audio=True,
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


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None
    or FFPROBE is None
    or not _has_x264_pixel_format("yuv420p10le"),
    reason="real H.264 High 10 regression requires 10-bit libx264 and ffprobe",
)
async def test_browser_video_transcodes_h264_high10_instead_of_remuxing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "high10.mp4"
    output = tmp_path / "browser.mp4"
    _make_h264_source(source, ten_bit=True)

    result = await FFmpegService().make_browser_video(source, output)

    assert result.success, result.error
    assert result.remuxed is False
    _assert_main_browser_output(output)


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None
    or FFPROBE is None
    or not _has_x264_pixel_format("yuv420p"),
    reason="real H.264 remux regression requires libx264 and ffprobe",
)
async def test_browser_video_remuxes_compatible_h264(tmp_path: Path) -> None:
    source = tmp_path / "main.mp4"
    output = tmp_path / "browser.mp4"
    _make_h264_source(source)

    result = await FFmpegService().make_browser_video(source, output)

    assert result.success, result.error
    assert result.remuxed is True
    _assert_main_browser_output(output)


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None
    or FFPROBE is None
    or not _has_x264_pixel_format("yuv420p"),
    reason="real compatible-cache regression requires libx264 and ffprobe",
)
async def test_ensure_clip_reuses_compatible_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sound_dir = tmp_path / "compatible"
    sound_dir.mkdir()
    source = sound_dir / "source.mp4"
    cache = sound_dir / "compatible_clip.mp4"
    _make_h264_source(source)
    shutil.copyfile(source, cache)
    _make_newer(cache, source)
    cached_bytes = cache.read_bytes()
    probed_paths: list[Path] = []
    real_probe = ffmpeg_service.probe

    async def counting_probe(path: Path) -> Any:
        probed_paths.append(path)
        return await real_probe(path)

    monkeypatch.setattr(ffmpeg_service, "probe", counting_probe)

    sound = _sound_for_video("compatible", source.name)
    result = await ensure_clip(sound, tmp_path)
    repeated = await ensure_clip(sound, tmp_path)

    assert result is not None
    assert result.generated is False
    assert cache.read_bytes() == cached_bytes
    assert repeated is not None
    assert repeated.generated is False
    assert probed_paths.count(cache) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None
    or FFPROBE is None
    or not _has_x264_pixel_format("yuv420p10le"),
    reason="real incompatible-cache regression requires 10-bit libx264 and ffprobe",
)
async def test_ensure_clip_regenerates_h264_high10_cache_atomically(
    tmp_path: Path,
) -> None:
    sound_dir = tmp_path / "incompatible"
    sound_dir.mkdir()
    source = sound_dir / "source.mp4"
    cache = sound_dir / "incompatible_clip.mp4"
    _make_h264_source(source, ten_bit=True)
    shutil.copyfile(source, cache)
    cache.chmod(0o640)
    _make_newer(cache, source)

    result = await ensure_clip(
        _sound_for_video("incompatible", source.name),
        tmp_path,
    )

    assert result is not None
    assert result.generated is True
    assert result.remuxed is False
    _assert_main_browser_output(cache)
    assert stat.S_IMODE(cache.stat().st_mode) == 0o640
    assert list(sound_dir.glob(".incompatible_clip-*.mp4")) == []


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None
    or FFPROBE is None
    or not _has_x264_pixel_format("yuv420p10le"),
    reason="real atomic-cache regression requires 10-bit libx264 and ffprobe",
)
async def test_failed_candidate_verification_preserves_existing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sound_dir = tmp_path / "retained"
    sound_dir.mkdir()
    source = sound_dir / "source.mp4"
    cache = sound_dir / "retained_clip.mp4"
    _make_h264_source(source, ten_bit=True)
    shutil.copyfile(source, cache)
    _make_newer(cache, source)
    cached_bytes = cache.read_bytes()

    async def fail_generation(
        input_file: Path,
        output_file: Path,
        start: float | None = None,
        end: float | None = None,
    ) -> ProcessResult:
        del input_file, start, end
        output_file.write_bytes(b"partial output")
        return ProcessResult(success=True, output_file=output_file)

    monkeypatch.setattr(ffmpeg_service, "make_browser_video", fail_generation)

    with pytest.raises(ClipError, match="does not satisfy browser-video"):
        await ensure_clip(_sound_for_video("retained", source.name), tmp_path)

    assert cache.read_bytes() == cached_bytes
    assert list(sound_dir.glob(".retained_clip-*.mp4")) == []


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="real trim timeline regression requires ffmpeg and ffprobe",
)
@pytest.mark.parametrize("trim_start", [3.25, 3.277])
async def test_non_keyframe_trim_preserves_visual_and_audio_timeline(
    tmp_path: Path, trim_start: float
) -> None:
    """Exercise the actual original -> trimmed MKV -> browser MP4 pipeline."""
    assert FFMPEG is not None
    from array import array

    from soundbot.models.sounds import Timestamps

    sound_dir = tmp_path / "timeline"
    sound_dir.mkdir()
    source = sound_dir / "original.mkv"
    trimmed = sound_dir / "trimmed.mkv"
    # A single 10-second GOP forces a seek into keyframe preroll. Two matching
    # flashes/beeps expose both the initial offset and an incorrectly cut tail.
    pulses = "between(t,4.25,4.49)+between(t,5.75,5.99)"
    _run(
        [
            FFMPEG, "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=black:size=160x90:rate=24:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=10",
            "-vf", f"drawbox=color=white:t=fill:enable='{pulses}'",
            "-af", f"volume=0:enable='not({pulses})'",
            "-c:v", "libx264", "-g", "240", "-sc_threshold", "0",
            "-pix_fmt", "yuv420p", "-c:a", "flac", source,
        ]
    )
    service = FFmpegService()
    result = await service.trim_video(
        source, trimmed, start=trim_start, end=trim_start + 3
    )
    assert result.success, result.error
    sound = Sound(
        directory="timeline",
        files=SoundFiles(
            original=source.name,
            trimmed_video=trimmed.name,
            trimmed_audio="unused.ogg",
        ),
        timestamps=Timestamps(start=trim_start, end=trim_start + 3),
        duration=3,
    )
    clip = await ensure_clip(sound, tmp_path)
    assert clip is not None and clip.generated

    for output in (trimmed, clip.path):
        probe = await service.probe(output)
        assert probe is not None and probe.duration is not None
        assert abs(probe.duration - 3) < 0.09

        video = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(output), "-an",
             "-vf", "scale=16:16,format=gray", "-f", "rawvideo", "pipe:1"],
            capture_output=True, check=True, timeout=30,
        ).stdout
        flash_frames = [
            index // 256
            for index in range(0, len(video), 256)
            if sum(video[index:index + 256]) / 256 > 100
        ]
        assert flash_frames
        assert abs(flash_frames[0] / 24 - (4.25 - trim_start)) < 0.09
        assert abs(flash_frames[-1] / 24 - (5.99 - trim_start)) < 0.09

        audio = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(output), "-vn",
             "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"],
            capture_output=True, check=True, timeout=30,
        ).stdout
        samples = array("f", audio)
        # 10ms windows avoid encoder ringing at the pulse boundaries.
        audible_windows = [
            index / 48000
            for index in range(0, len(samples) - 480, 480)
            if sum(value * value for value in samples[index:index + 480]) / 480 > 0.001
        ]
        assert audible_windows
        assert abs(audible_windows[0] - (4.25 - trim_start)) < 0.04
        assert abs(audible_windows[-1] - (5.99 - trim_start)) < 0.04
        assert abs(flash_frames[0] / 24 - audible_windows[0]) < 0.09


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="real odd-dimension trim regression requires ffmpeg and ffprobe",
)
async def test_accurate_trim_pads_odd_source_dimensions(tmp_path: Path) -> None:
    assert FFMPEG is not None
    source = tmp_path / "odd.mkv"
    output = tmp_path / "trimmed.mkv"
    _run(
        [
            FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc=size=161x91:rate=24:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv444p", source,
        ]
    )
    result = await FFmpegService().trim_video(source, output, start=0.25, end=0.75)
    assert result.success, result.error
    video = next(
        stream for stream in _probe_streams(output)
        if stream["codec_type"] == "video"
    )
    assert (video["width"], video["height"], video["pix_fmt"]) == (162, 92, "yuv420p")


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="real 4K trim regression requires ffmpeg and ffprobe",
)
async def test_accurate_trim_uses_browser_width_for_4k_intermediate(tmp_path: Path) -> None:
    assert FFMPEG is not None
    source = tmp_path / "4k.mkv"
    output = tmp_path / "trimmed.mkv"
    _run(
        [
            FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=size=3840x2160:rate=24:duration=0.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2", source,
        ]
    )
    result = await FFmpegService().trim_video(source, output, start=0.1, end=0.4)
    assert result.success, result.error
    video = next(
        stream for stream in _probe_streams(output)
        if stream["codec_type"] == "video"
    )
    assert (video["width"], video["height"], video["pix_fmt"]) == (1280, 720, "yuv420p")
