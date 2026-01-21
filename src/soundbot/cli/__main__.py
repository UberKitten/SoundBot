"""CLI entry point for SoundBot utilities."""

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="soundbot-cli",
        description="SoundBot CLI utilities",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Regenerate audio command
    regen_parser = subparsers.add_parser(
        "regenerate-audio",
        help="Regenerate trimmed audio files for all sounds",
    )
    _ = regen_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be regenerated without actually doing it",
    )
    _ = regen_parser.add_argument(
        "--sound",
        type=str,
        help="Regenerate only a specific sound by name",
    )

    # Check sounds command
    check_parser = subparsers.add_parser(
        "check-sounds",
        help="Check for sounds with missing audio files",
    )
    _ = check_parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove broken entries from state (doesn't delete files)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "regenerate-audio":
        from soundbot.cli.regenerate_audio import regenerate_audio_files

        asyncio.run(
            regenerate_audio_files(
                dry_run=args.dry_run,
                sound_name=args.sound,
            )
        )
    elif args.command == "check-sounds":
        from soundbot.cli.check_sounds import check_sounds

        check_sounds(remove_broken=args.remove)


if __name__ == "__main__":
    main()
