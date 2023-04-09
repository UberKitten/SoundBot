import logging

from app.discord.client import client
from app.core.settings import settings


if __name__ == "__main__":
    logging.basicConfig(encoding='utf-8', level=logging.DEBUG)
    
    client.run(settings.token)

