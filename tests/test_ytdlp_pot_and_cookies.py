"""Focused contracts for yt-dlp POT provider and cookie fallback behavior."""

import logging
from pathlib import Path

import pytest

import soundbot.services.ytdlp as ytdlp_module
from soundbot.core.settings import settings
from soundbot.services.ytdlp import DownloadResult, YtdlpService


@pytest.fixture(autouse=True)
def ytdlp_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "ytdlp_pot_provider_url", "http://192.168.0.10:4416"
    )
    monkeypatch.setattr(settings, "ytdlp_cookies_file", None)
    monkeypatch.setattr(
        ytdlp_module,
        "_get_ytdlp_command",
        lambda: ["python", "-m", "yt_dlp"],
    )


def test_download_and_metadata_args_include_provider_and_existing_options() -> None:
    download_args = ytdlp_module._build_download_args(
        "https://www.youtube.com/watch?v=test", "sound.%(ext)s"
    )
    info_args = ytdlp_module._build_video_info_args(
        "https://www.youtube.com/watch?v=test"
    )
    expected_extractor_args = [
        "youtube:player_client=mweb",
        "youtubepot-bgutilhttp:base_url=http://192.168.0.10:4416",
    ]

    for args in (download_args, info_args):
        assert [
            args[index + 1]
            for index, value in enumerate(args)
            if value == "--extractor-args"
        ] == expected_extractor_args
        assert args[args.index("--js-runtimes") + 1] == "node"
        assert args[args.index("--remote-components") + 1] == "ejs:github"
        assert "--cookies" not in args

    assert download_args[download_args.index("--format") + 1] == (
        "bestvideo+bestaudio/best/bestaudio"
    )
    assert download_args[download_args.index("--merge-output-format") + 1] == "mkv"
    assert {
        "--no-playlist",
        "--write-info-json",
        "--embed-metadata",
        "--no-overwrites",
        "--print-json",
    }.issubset(download_args)
    assert {"--dump-json", "--no-download"}.issubset(info_args)


def test_provider_args_use_configured_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "ytdlp_pot_provider_url", "http://provider.internal:4416"
    )

    args = ytdlp_module._build_video_info_args("https://youtu.be/test")

    extractor_args = [
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--extractor-args"
    ]
    assert extractor_args[-1] == (
        "youtubepot-bgutilhttp:base_url=http://provider.internal:4416"
    )


@pytest.mark.asyncio
async def test_download_succeeds_anonymously_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = YtdlpService()
    cookie_attempts: list[Path | None] = []

    async def fake_download(
        url: str,
        output_dir: Path,
        sound_name: str,
        *,
        cookies_file: Path | None = None,
    ) -> DownloadResult:
        cookie_attempts.append(cookies_file)
        return DownloadResult(success=True)

    async def unexpected_update() -> tuple[bool, str]:
        raise AssertionError("successful anonymous downloads must not update yt-dlp")

    monkeypatch.setattr(service, "_do_download", fake_download)
    monkeypatch.setattr(service, "update_ytdlp", unexpected_update)

    result = await service.download("https://youtu.be/test", tmp_path, "sound")

    assert result.success
    assert cookie_attempts == [None]


@pytest.mark.asyncio
async def test_download_retries_once_with_cookies_when_file_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = YtdlpService()
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.touch()
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies_file))
    cookie_attempts: list[Path | None] = []

    async def fake_download(
        url: str,
        output_dir: Path,
        sound_name: str,
        *,
        cookies_file: Path | None = None,
    ) -> DownloadResult:
        cookie_attempts.append(cookies_file)
        return DownloadResult(success=False, error="blocked")

    async def failed_update() -> tuple[bool, str]:
        return False, "offline"

    monkeypatch.setattr(service, "_do_download", fake_download)
    monkeypatch.setattr(service, "update_ytdlp", failed_update)

    result = await service.download("https://youtu.be/test", tmp_path, "sound")

    assert not result.success
    assert cookie_attempts == [None, cookies_file]


@pytest.mark.asyncio
async def test_missing_cookie_file_never_adds_cookie_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = YtdlpService()
    missing_file = tmp_path / "missing-cookies.txt"
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(missing_file))
    cookie_attempts: list[Path | None] = []

    async def fake_download(
        url: str,
        output_dir: Path,
        sound_name: str,
        *,
        cookies_file: Path | None = None,
    ) -> DownloadResult:
        cookie_attempts.append(cookies_file)
        return DownloadResult(success=False, error="blocked")

    async def successful_update() -> tuple[bool, str]:
        return True, "updated"

    monkeypatch.setattr(service, "_do_download", fake_download)
    monkeypatch.setattr(service, "update_ytdlp", successful_update)

    result = await service.download("https://youtu.be/test", tmp_path, "sound")

    assert not result.success
    assert not missing_file.exists()
    assert cookie_attempts == [None, None]


@pytest.mark.asyncio
async def test_video_info_is_anonymous_first_then_retries_once_with_cookies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = YtdlpService()
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.touch()
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies_file))
    cookie_attempts: list[Path | None] = []

    async def fake_video_info(
        url: str, cookies_file: Path | None = None
    ) -> tuple[dict[str, object] | None, str | None]:
        cookie_attempts.append(cookies_file)
        if cookies_file is None:
            return None, "anonymous blocked"
        return {"title": "available"}, None

    monkeypatch.setattr(service, "_get_video_info_once", fake_video_info)

    info = await service.get_video_info("https://youtu.be/test")

    assert info == {"title": "available"}
    assert cookie_attempts == [None, cookies_file]


@pytest.mark.asyncio
async def test_video_info_missing_cookie_file_stays_anonymous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = YtdlpService()
    missing_file = tmp_path / "missing-cookies.txt"
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(missing_file))
    cookie_attempts: list[Path | None] = []

    async def fake_video_info(
        url: str, cookies_file: Path | None = None
    ) -> tuple[dict[str, object] | None, str | None]:
        cookie_attempts.append(cookies_file)
        return None, "blocked"

    monkeypatch.setattr(service, "_get_video_info_once", fake_video_info)

    assert await service.get_video_info("https://youtu.be/test") is None
    assert cookie_attempts == [None]


@pytest.mark.asyncio
async def test_cookie_path_is_redacted_from_failure_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = YtdlpService()
    cookies_file = tmp_path / "private-cookies.txt"
    captured_args: tuple[object, ...] = ()

    class FailedProcess:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", f"failed to open {cookies_file}".encode()

    async def fake_subprocess(*args: object, **kwargs: object) -> FailedProcess:
        nonlocal captured_args
        captured_args = args
        return FailedProcess()

    monkeypatch.setattr(
        ytdlp_module.asyncio, "create_subprocess_exec", fake_subprocess
    )
    caplog.set_level(logging.DEBUG, logger=ytdlp_module.__name__)

    result = await service._do_download(
        "https://youtu.be/test",
        tmp_path / "output",
        "sound",
        cookies_file=cookies_file,
    )

    assert not result.success
    assert result.error == "failed to open <cookies-file>"
    assert str(cookies_file) not in caplog.text
    assert "<cookies-file>" in caplog.text
    cookie_index = captured_args.index("--cookies")
    assert captured_args[cookie_index + 1] == str(cookies_file)
