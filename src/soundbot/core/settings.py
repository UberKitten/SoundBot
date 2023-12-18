from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    token: str

    # Used for local command registration
    test_guild_ids: Optional[str] = None  # comma separated

    state_file: str = "mount/state.json"
    db_file: str = "mount/db.json"

    static_folder: str = "web/dist"
    templates_folder: str = "web/template"

    sounds_folder: str = "mount/sounds"


settings = Settings()
