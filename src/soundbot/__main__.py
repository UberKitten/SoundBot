import logging

import uvloop

if __name__ == "__main__":
    logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

    # Import app first which creates most loggers
    from soundbot.app import run

    # Silence other loggers
    for name, logger in logging.Logger.manager.loggerDict.items():
        if not name.startswith("app"):
            if hasattr(logger, "setLevel"):
                logger.setLevel(logging.CRITICAL)

    uvloop.run(run())
