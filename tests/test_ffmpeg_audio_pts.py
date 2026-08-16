import asyncio
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from soundbot.core.settings import settings
from soundbot.services.ffmpeg import FFmpegService, ProbeResult

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
GAP_THRESHOLD = Fraction(1, 1000)
VOLUME_DB = -1.5


class SuccessfulProcess:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


def _run(command: list[str | Path]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(argument) for argument in command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result


def _probe_json(path: Path, entries: str, *sections: str) -> dict[str, Any]:
    assert FFPROBE is not None
    result = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            *sections,
            "-show_entries",
            entries,
            "-of",
            "json",
            path,
        ]
    )
    return json.loads(result.stdout)


def _positive_packet_gaps(path: Path) -> list[Fraction]:
    probe = _probe_json(
        path,
        "packet=pts,duration:stream=time_base",
        "-show_packets",
        "-show_streams",
    )
    time_base = Fraction(probe["streams"][0]["time_base"])
    packets = [
        (int(packet["pts"]), int(packet["duration"]))
        for packet in probe["packets"]
        if "pts" in packet and "duration" in packet
    ]
    assert len(packets) >= 2
    return [
        gap
        for (pts, duration), (next_pts, _) in zip(packets, packets[1:])
        if (gap := (next_pts - pts - duration) * time_base) > 0
    ]


def _make_partial_frame_source(tmp_path: Path) -> Path:
    assert FFMPEG is not None
    source = tmp_path / "partial-frame.wav"
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
            "sine=frequency=997:sample_rate=48000:duration=3.924",
            "-c:a",
            "pcm_s16le",
            source,
        ]
    )
    return source


@pytest.mark.asyncio
async def test_audio_pts_compaction_is_the_final_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def create_process(*args: str, **_kwargs: Any) -> SuccessfulProcess:
        calls.append(args)
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    async def probe(_path: Path) -> ProbeResult:
        return ProbeResult(duration=3.924, has_audio=True)

    service = FFmpegService()
    monkeypatch.setattr(service, "probe", probe)

    result = await service.extract_and_normalize_audio(
        tmp_path / "input.mkv",
        tmp_path / "output.ogg",
        volume_db=VOLUME_DB,
    )

    assert result.success
    filter_graph = calls[0][calls[0].index("-af") + 1]
    assert filter_graph == (
        f"loudnorm=I={settings.audio_target_lufs}:TP=-1.5:LRA=11,"
        f"volume={VOLUME_DB}dB,asetpts=N/SR/TB"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="real FFmpeg regression requires ffmpeg and ffprobe",
)
async def test_audio_pts_compaction_closes_real_loudnorm_packet_gap(
    tmp_path: Path,
) -> None:
    assert FFMPEG is not None
    source = _make_partial_frame_source(tmp_path)
    baseline = tmp_path / "without-compaction.ogg"
    fixed = tmp_path / "with-compaction.ogg"
    loudnorm = f"loudnorm=I={settings.audio_target_lufs}:TP=-1.5:LRA=11"

    _run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-af",
            f"{loudnorm},volume={VOLUME_DB}dB",
            "-vn",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            baseline,
        ]
    )
    baseline_gaps = _positive_packet_gaps(baseline)
    assert any(gap >= GAP_THRESHOLD for gap in baseline_gaps), baseline_gaps

    result = await FFmpegService().extract_and_normalize_audio(
        source,
        fixed,
        volume_db=VOLUME_DB,
    )
    assert result.success, result.error

    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-i",
            fixed,
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ]
    )
    metadata = _probe_json(
        fixed,
        "stream=codec_name,sample_rate,channels:format=format_name",
    )
    assert metadata["format"]["format_name"] == "ogg"
    assert metadata["streams"] == [
        {"codec_name": "opus", "sample_rate": "48000", "channels": 2}
    ]
    assert not [
        gap for gap in _positive_packet_gaps(fixed) if gap >= GAP_THRESHOLD
    ]
