import asyncio
import logging
import sys

if __name__ == "__main__":
    logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

    # Import app first which creates most loggers
    from soundbot.app import run

    # Silence other loggers
    for name, logger in logging.Logger.manager.loggerDict.items():
        if not name.startswith("app"):
            if hasattr(logger, "setLevel"):
                logger.setLevel(logging.CRITICAL)

    # Use uvloop on Unix platforms for better performance
    if sys.platform != "win32":
        try:
            import uvloop

            uvloop.run(run())
        except ImportError:
            asyncio.run(run())
    else:
        asyncio.run(run())
