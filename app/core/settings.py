from typing import Optional
from pydantic import BaseSettings


class Settings(BaseSettings):
    class Config:
        env_file = '.env'

    token: str

    # Used for local command registration
    test_guild_ids: Optional[str] = None # comma separated
    
    web_static_root = "app/web/static/"
    web_templates_root = "app/web/template/"

    sounds_root = "mount/sounds/"


settings = Settings()