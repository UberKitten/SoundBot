from typing import Optional
from pydantic import BaseSettings


class Settings(BaseSettings):
    class Config:
        env_file = '.env'

    token: str

    # Used for local command registration
    test_guild_ids: Optional[str] = None # comma separated

settings = Settings()