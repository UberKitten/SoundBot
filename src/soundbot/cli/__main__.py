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

    # Export command
    export_parser = subparsers.add_parser(
        "export-history",
        help="Export Discord channel message history to a JSON file",
    )
    export_parser.add_argument(
        "channel_id",
        type=int,
        help="The Discord channel ID to export history from",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="mount/channel_history.json",
        help="Output file path (default: mount/channel_history.json)",
    )
    export_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of messages to fetch (default: all)",
    )

    # Parse legacy sounds command
    parse_parser = subparsers.add_parser(
        "parse-legacy",
        help="Parse exported history and extract legacy sound commands",
    )
    parse_parser.add_argument(
        "-i",
        "--input",
        type=str,
        default="mount/channel_history.json",
        help="Input history file (default: mount/channel_history.json)",
    )
    parse_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="mount/legacy_sounds.json",
        help="Output file for parsed sounds (default: mount/legacy_sounds.json)",
    )

    # Import legacy sounds command
    import_parser = subparsers.add_parser(
        "import-legacy",
        help="Import legacy sounds from parsed commands file",
    )
    import_parser.add_argument(
        "-i",
        "--input",
        type=str,
        default="mount/legacy_sounds.json",
        help="Input file with parsed sounds (default: mount/legacy_sounds.json)",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without actually importing",
    )
    import_parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip sounds that already exist (default: True)",
    )
    import_parser.add_argument(
        "--sound",
        type=str,
        help="Import only a specific sound by name",
    )

    # Regenerate audio command
    regen_parser = subparsers.add_parser(
        "regenerate-audio",
        help="Regenerate trimmed audio files for all non-legacy sounds",
    )
    regen_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be regenerated without actually doing it",
    )
    regen_parser.add_argument(
        "--sound",
        type=str,
        help="Regenerate only a specific sound by name",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "export-history":
        from soundbot.cli.export_history import export_channel_history

        asyncio.run(
            export_channel_history(
                channel_id=args.channel_id,
                output_path=args.output,
                limit=args.limit,
            )
        )
    elif args.command == "parse-legacy":
        from soundbot.cli.parse_legacy import parse_legacy_commands

        parse_legacy_commands(
            input_path=args.input,
            output_path=args.output,
        )
    elif args.command == "import-legacy":
        from soundbot.cli.import_legacy import import_legacy_sounds

        asyncio.run(
            import_legacy_sounds(
                input_path=args.input,
                dry_run=args.dry_run,
                skip_existing=args.skip_existing,
                sound_name=args.sound,
            )
        )
    elif args.command == "regenerate-audio":
        from soundbot.cli.regenerate_audio import regenerate_audio_files

        asyncio.run(
            regenerate_audio_files(
                dry_run=args.dry_run,
                sound_name=args.sound,
            )
        )


if __name__ == "__main__":
    main()
