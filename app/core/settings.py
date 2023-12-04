from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    token: str

    # Used for local command registration
    test_guild_ids: Optional[str] = None  # comma separated

    web_static_root: str = "app/web/static/"
    web_templates_root: str = "app/web/template/"

    sounds_root: str = "mount/sounds/"


settings = Settings()
