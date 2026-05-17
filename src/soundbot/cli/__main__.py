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

    # Clip command
    clip_parser = subparsers.add_parser(
        "clip",
        help="Create a sound by clipping a local video file (no copy of source)",
    )
    _ = clip_parser.add_argument("video", type=str, help="Path to video file")
    _ = clip_parser.add_argument("name", type=str, help="Sound name")
    _ = clip_parser.add_argument(
        "start", type=str, help="Start time (HH:MM:SS, MM:SS, or seconds)"
    )
    _ = clip_parser.add_argument(
        "end", type=str, help="End time (HH:MM:SS, MM:SS, or seconds)"
    )
    _ = clip_parser.add_argument(
        "--volume",
        type=int,
        default=0,
        help="Volume adjustment in notches (-5 to +3, each notch = 3dB)",
    )
    _ = clip_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing sound with the same name",
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
    elif args.command == "clip":
        from soundbot.cli.clip import clip_video

        exit_code = asyncio.run(
            clip_video(
                video=args.video,
                start=args.start,
                end=args.end,
                name=args.name,
                volume_adjust=args.volume,
                overwrite=args.overwrite,
            )
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
