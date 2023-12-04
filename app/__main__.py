import logging

from app.core.settings import settings
from app.discord.client import soundbot_client

if __name__ == "__main__":
    logging.basicConfig(encoding="utf-8", level=logging.DEBUG)

    soundbot_client.run(settings.token)
