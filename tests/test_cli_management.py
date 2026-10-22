"""Native CLI behavior, including a real-media full-source/trim/group round trip."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from soundbot.cli.manage import register_commands, run
from soundbot.core.state import state
from soundbot.services.sounds import OperationResult, sound_service
from tests.conftest import make_sound

PROJECT = Path(__file__).resolve().parents[1]


def _args(*arguments: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    register_commands(parser.add_subparsers(dest="command", required=True))
    return parser.parse_args(arguments)


def _output(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


async def test_url_add_always_stages_full_length(monkeypatch, capsys) -> None:
    add = AsyncMock(return_value=OperationResult(True, "added"))
    monkeypatch.setattr(sound_service, "add_sound", add)
    assert await run(_args("add", "Friday", "https://example.test/report")) == 0
    add.assert_awaited_once_with("Friday", "https://example.test/report")
    assert _output(capsys)["success"] is True


async def test_local_import_copies_full_source_with_provenance(monkeypatch, tmp_path) -> None:
    add = AsyncMock(return_value=OperationResult(True, "added"))
    monkeypatch.setattr(sound_service, "add_sound_from_local_file", add)
    source = tmp_path / "report.mkv"
    assert await run(_args("import-file", "Friday", str(source), "--source-url", "https://example.test/report", "--source-title", "Report 2022-12-16")) == 0
    add.assert_awaited_once_with(
        "Friday", source,
        source_url="https://example.test/report", source_title="Report 2022-12-16",
    )


async def test_trim_resolves_exact_alias_without_downloading(monkeypatch) -> None:
    state.sounds["friday"] = make_sound(aliases=["fri"])
    edit = AsyncMock(return_value=OperationResult(True, "trimmed"))
    download = AsyncMock(side_effect=AssertionError("trim must never download"))
    monkeypatch.setattr(sound_service, "edit_timestamps", edit)
    monkeypatch.setattr(sound_service, "add_sound", download)
    assert await run(_args("trim", "FRI", "0:10.25", "0:18.5")) == 0
    edit.assert_awaited_once_with("friday", start=10.25, end=18.5)
    download.assert_not_awaited()


@pytest.mark.parametrize("start,end", [("nan", "20"), ("0", "inf"), ("-1", "3"), ("2", "2"), ("3", "2"), ("bad", "3")])
async def test_invalid_trim_never_calls_service(monkeypatch, start, end, capsys) -> None:
    state.sounds["friday"] = make_sound()
    edit = AsyncMock()
    monkeypatch.setattr(sound_service, "edit_timestamps", edit)
    assert await run(_args("trim", "friday", start, end)) == 1
    edit.assert_not_awaited()
    assert _output(capsys)["success"] is False


async def test_groups_use_exact_names_and_existing_service(capsys) -> None:
    state.sounds["friday"] = make_sound(aliases=["fri"])
    assert await run(_args("group", "add", "Fridays", "frid")) == 1
    assert "fridays" not in state.groups
    assert _output(capsys)["success"] is False
    assert await run(_args("group", "create", "Fridays")) == 0
    _output(capsys)
    assert await run(_args("group", "add", "FRIDAYS", "FRI")) == 0
    _output(capsys)
    assert await run(_args("group", "add", "fridays", "friday")) == 1
    _output(capsys)
    assert state.groups["fridays"].members == ["friday"]
    assert await run(_args("group", "list")) == 0
    assert _output(capsys)["groups"]["fridays"]["members"] == ["friday"]
    assert await run(_args("group", "list", "FRIDAYS")) == 0
    assert _output(capsys)["members"] == ["friday"]
    assert await run(_args("group", "remove", "fridays", "fri")) == 0
    _output(capsys)
    assert await run(_args("group", "delete", "fridays")) == 0
    _output(capsys)
    assert state.groups == {}


async def test_inspection_and_delete_guard_preserve_group_references(monkeypatch, capsys) -> None:
    state.sounds["friday"] = make_sound(source_url="https://example.test/report")
    sound_service.add_to_group("fridays", "friday")
    assert await run(_args("info", "FRIDAY")) == 0
    info = _output(capsys)
    assert info["name"] == "friday"
    assert info["source_url"] == "https://example.test/report"
    assert info["groups"] == ["fridays"]
    assert "original" in info["paths"]
    assert await run(_args("list")) == 0
    listing = _output(capsys)
    assert listing["sounds"][0]["name"] == "friday"
    assert listing["groups"]["fridays"]["members"] == ["friday"]
    delete = AsyncMock(return_value=OperationResult(True, "deleted"))
    monkeypatch.setattr(sound_service, "delete_sound", delete)
    assert await run(_args("delete", "friday")) == 1
    _output(capsys)
    assert await run(_args("delete", "friday", "--yes")) == 1
    assert "memberships" in _output(capsys)["message"]
    delete.assert_not_awaited()
    sound_service.remove_from_group("fridays", "friday")
    assert await run(_args("delete", "friday", "--yes")) == 0
    delete.assert_awaited_once_with("friday")


def _environment(root: Path) -> dict[str, str]:
    return {
        **os.environ,
        "TOKEN": "test-token-not-real",
        "STATE_FILE": str(root / "state.json"),
        "SOUNDS_FOLDER": str(root / "sounds"),
        "PYTHONPATH": str(PROJECT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _cli(root: Path, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-B", "-m", "soundbot.cli", *arguments],
        cwd=root, env=_environment(root), capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return result


@pytest.mark.parametrize("console", [False, True])
def test_help_is_lazy_and_console_entrypoint_works(tmp_path, console) -> None:
    environment = _environment(tmp_path)
    environment.pop("TOKEN")
    command = [sys.executable, "-B"]
    command += ["-c", "from soundbot.cli import main; main()"] if console else ["-m", "soundbot.cli"]
    result = subprocess.run(command + ["--help"], cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "import-file" in result.stdout
    assert "group" in result.stdout
    assert not (tmp_path / "state.lock").exists()
    assert not (tmp_path / "state.json").exists()


def test_management_refuses_live_state_lock(tmp_path) -> None:
    lock = tmp_path / "state.lock"
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _cli(tmp_path, "group", "create", "fridays", expected=1)
        assert "could not acquire lock" in result.stderr
        assert not (tmp_path / "state.json").exists()


def test_real_media_full_import_trim_group_round_trip(tmp_path) -> None:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and ffprobe required for real-media CLI regression")
    source = tmp_path / "report.mp4"
    generated = subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
        capture_output=True, text=True, timeout=30,
    )
    assert generated.returncode == 0, generated.stderr
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    full = json.loads(_cli(tmp_path, "import-file", "Friday20221216", str(source), "--source-url", "https://example.test/report", "--source-title", "Report 2022-12-16").stdout)
    assert full["success"] is True
    sound = full["sound"]
    assert sound["timestamps"] == {"start": None, "end": None}
    assert sound["source_url"] == "https://example.test/report"
    assert sound["source_duration"] == pytest.approx(2, abs=0.1)
    assert sound["duration"] == pytest.approx(2, abs=0.05)
    original = Path(sound["paths"]["original"]["path"])
    assert original != source
    assert hashlib.sha256(original.read_bytes()).hexdigest() == source_hash
    duplicate = _cli(tmp_path, "import-file", "friday20221216", str(source), expected=1)
    assert json.loads(duplicate.stdout)["success"] is False
    trimmed = json.loads(_cli(tmp_path, "trim", "FRIDAY20221216", "0.5", "1.5").stdout)["sound"]
    assert trimmed["timestamps"] == {"start": 0.5, "end": 1.5}
    assert trimmed["duration"] == pytest.approx(1, abs=0.05)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    for role in ("audio", "video", "clip"):
        media = trimmed["paths"][role]
        assert media["exists"] is True
        decoded = subprocess.run([ffmpeg, "-v", "error", "-xerror", "-i", media["path"], "-f", "null", "-"], capture_output=True, text=True, timeout=30)
        assert decoded.returncode == 0, decoded.stderr
        probed = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", media["path"]], capture_output=True, text=True, timeout=20)
        assert probed.returncode == 0, probed.stderr
        assert float(json.loads(probed.stdout)["format"]["duration"]) == pytest.approx(1, abs=0.08)
    _cli(tmp_path, "group", "create", "lynchfridays")
    _cli(tmp_path, "group", "add", "lynchfridays", "friday20221216")
    grouped = json.loads(_cli(tmp_path, "group", "list", "lynchfridays").stdout)
    assert grouped["members"] == ["friday20221216"]
    _cli(tmp_path, "delete", "friday20221216", "--yes", expected=1)
    assert original.exists()
    _cli(tmp_path, "group", "remove", "lynchfridays", "friday20221216")
    _cli(tmp_path, "group", "delete", "lynchfridays")
    _cli(tmp_path, "delete", "friday20221216", "--yes")
    listing = json.loads(_cli(tmp_path, "list").stdout)
    assert listing == {"sounds": [], "groups": {}}
    assert source.exists()
    assert not original.exists()
