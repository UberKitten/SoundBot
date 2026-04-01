import asyncio
import logging
import sys

if __name__ == "__main__":
    logging.basicConfig(
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    web_only = "--web-only" in sys.argv

    # Import app first which creates most loggers
    from soundbot.app import run, run_web_only

    # Silence noisy third-party loggers
    # logging.getLogger("discord").setLevel(logging.WARNING)
    # logging.getLogger("discord.http").setLevel(logging.WARNING)
    # logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    # logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("hypercorn").setLevel(logging.WARNING)
    logging.getLogger("hypercorn.access").setLevel(logging.WARNING)

    entry = run_web_only if web_only else run

    # Use uvloop on Unix platforms for better performance
    if sys.platform != "win32":
        try:
            import uvloop  # type: ignore[import-not-found]

            uvloop.run(entry())
        except ImportError:
            asyncio.run(entry())
    else:
        asyncio.run(entry())
