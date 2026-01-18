import asyncio
import logging
import sys

if __name__ == "__main__":
    logging.basicConfig(
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Import app first which creates most loggers
    from soundbot.app import run

    # Silence noisy third-party loggers
    # logging.getLogger("discord").setLevel(logging.WARNING)
    # logging.getLogger("discord.http").setLevel(logging.WARNING)
    # logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    # logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("hypercorn").setLevel(logging.WARNING)
    logging.getLogger("hypercorn.access").setLevel(logging.WARNING)

    # Use uvloop on Unix platforms for better performance
    if sys.platform != "win32":
        try:
            import uvloop

            uvloop.run(run())
        except ImportError:
            asyncio.run(run())
    else:
        asyncio.run(run())
