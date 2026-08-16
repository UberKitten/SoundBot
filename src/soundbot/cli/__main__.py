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

    backfill_parser = subparsers.add_parser(
        "backfill-durations",
        help="Validate and backfill final playable OGG durations",
    )
    _ = backfill_parser.add_argument("--state-file", type=str)
    _ = backfill_parser.add_argument("--sounds-folder", type=str)
    _ = backfill_parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically write the fully validated backfill",
    )
    _ = backfill_parser.add_argument(
        "--repair-duplicates",
        action="store_true",
        help="Copy duplicate playable storage to deterministic unique directories",
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
    elif args.command == "backfill-durations":
        from pathlib import Path

        from soundbot.cli.backfill_durations import backfill_durations
        from soundbot.core.settings import settings

        state_file = Path(args.state_file or settings.state_file)
        sounds_folder = Path(args.sounds_folder or settings.sounds_folder)
        try:
            result = asyncio.run(
                backfill_durations(
                    state_file,
                    sounds_folder,
                    write=args.write,
                    repair_duplicates=args.repair_duplicates,
                )
            )
        except Exception as e:
            print(f"Duration backfill failed: {e}")
            sys.exit(1)
        action = "Backfilled" if args.write else "Validated"
        print(f"{action} {len(result.durations)} playable OGG durations")
        if result.repairs:
            print(f"Repaired {len(result.repairs)} duplicate playable paths")
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
