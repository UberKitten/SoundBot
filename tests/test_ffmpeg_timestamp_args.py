import asyncio
from pathlib import Path
from typing import Any

import pytest

from soundbot.models.sounds import Timestamps
from soundbot.services.ffmpeg import (
    FFmpegService,
    ProbeResult,
    format_ffmpeg_timestamp,
)
from soundbot.web.routes.admin import AddSoundBody, TrimBody
from soundbot.web.routes.drafts import CommitDraftBody


class SuccessfulProcess:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


@pytest.fixture(autouse=True)
def verified_playable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def probe(_self: FFmpegService, _path: Path) -> ProbeResult:
        return ProbeResult(duration=3.875, has_audio=True)

    monkeypatch.setattr(FFmpegService, "probe", probe)


def argument_after(args: tuple[str, ...], flag: str) -> str:
    return args[args.index(flag) + 1]


@pytest.mark.parametrize("boundary", [1.0408340855860843e-16, -1.0408340855860843e-16])
def test_trim_request_models_canonicalize_near_zero_boundaries(boundary: float) -> None:
    add = AddSoundBody(
        name="test", url="https://example.test", start=boundary, end=boundary
    )
    trim = TrimBody(start=boundary, end=boundary)
    commit = CommitDraftBody(name="test", start=boundary, end=boundary)
    timestamps = Timestamps(start=boundary, end=boundary)
    for model in (add, trim, commit, timestamps):
        assert model.start == 0
        assert model.end == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ["extract_and_normalize_audio", "trim_video", "make_browser_video"],
)
@pytest.mark.parametrize("start", [1.0408340855860843e-16, -1.0408340855860843e-16])
async def test_trim_argv_canonicalizes_near_zero_without_exponents(
    method_name: str,
    start: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def create_process(*args: str, **_kwargs: Any) -> SuccessfulProcess:
        calls.append(args)
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    service = FFmpegService()
    result = await getattr(service, method_name)(
        tmp_path / "input.mkv",
        tmp_path / "output.ogg",
        start=start,
        end=3.875,
    )

    assert result.success
    assert len(calls) == 1
    assert argument_after(calls[0], "-ss") == "0"
    assert argument_after(calls[0], "-t") == "3.875"
    assert all("e" not in value.lower() for value in calls[0] if value[0:1].isdigit())

@pytest.mark.asyncio
@pytest.mark.parametrize("end", [1.0408340855860843e-16, -1.0408340855860843e-16])
async def test_trim_argv_canonicalizes_near_zero_end_without_exponents(
    end: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def create_process(*args: str, **_kwargs: Any) -> SuccessfulProcess:
        calls.append(args)
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    result = await FFmpegService().extract_and_normalize_audio(
        tmp_path / "input.mkv",
        tmp_path / "output.ogg",
        end=end,
    )

    assert result.success
    assert "-ss" not in calls[0]
    assert argument_after(calls[0], "-t") == "0"

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ["extract_and_normalize_audio", "trim_video", "make_browser_video"],
)
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (float("-inf"), 1.0),
        (-1e308, 1e308),
    ],
)
async def test_invalid_trim_times_return_failed_result_without_spawning_ffmpeg(
    method_name: str,
    start: float,
    end: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_process(*_args: str, **_kwargs: Any) -> SuccessfulProcess:
        raise AssertionError("FFmpeg must not start for invalid timestamps")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_process)

    result = await getattr(FFmpegService(), method_name)(
        tmp_path / "input.mkv",
        tmp_path / "output.ogg",
        start=start,
        end=end,
    )

    assert not result.success
    assert result.error == "Trim timestamps must be finite"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (0.123456789, 3.987654321),
        (123456789.1234567, 123456790.9876543),
    ],
)
async def test_trim_argv_preserves_fractional_and_long_boundaries(
    start: float,
    end: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def create_process(*args: str, **_kwargs: Any) -> SuccessfulProcess:
        calls.append(args)
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    result = await FFmpegService().extract_and_normalize_audio(
        tmp_path / "input.mkv",
        tmp_path / "output.ogg",
        start=start,
        end=end,
    )

    assert result.success
    start_arg = argument_after(calls[0], "-ss")
    duration_arg = argument_after(calls[0], "-t")
    assert start_arg == format_ffmpeg_timestamp(start)
    assert duration_arg == format_ffmpeg_timestamp(end - start)
    assert float(start_arg) == start
    assert float(duration_arg) == end - start
    assert "e" not in start_arg.lower()
    assert "e" not in duration_arg.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [0.00001, 123456789.1234567])
async def test_waveform_video_argv_preserves_duration_without_exponents(
    duration: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def create_process(*args: str, **_kwargs: Any) -> SuccessfulProcess:
        calls.append(args)
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    result = await FFmpegService().make_waveform_video(
        tmp_path / "input.ogg",
        tmp_path / "output.mp4",
        duration,
    )

    assert result.success
    duration_arg = format_ffmpeg_timestamp(duration)
    render_args = calls[-1]
    assert [render_args[index + 1] for index, value in enumerate(render_args) if value == "-t"] == [
        duration_arg,
        duration_arg,
        duration_arg,
    ]
    filter_graph = argument_after(render_args, "-filter_complex")
    assert f"duration={duration_arg}:offset=0" in filter_graph
    assert "e" not in duration_arg.lower()
