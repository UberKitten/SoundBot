"""CLI module for SoundBot utilities."""


def main() -> None:
    """Installed console entry point; keep --help free of state imports."""
    from soundbot.cli.__main__ import main as run_main

    run_main()
