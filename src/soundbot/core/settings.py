from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    token: str  # Loaded from .env or environment variables

    # Used for local command registration
    test_guild_ids: Optional[str] = None  # comma separated

    state_file: str = "config/state.json"

    static_folder: str = "web/dist"
    templates_folder: str = "web/template"

    sounds_folder: str = "sounds"

    web_ui_url: str = "sounds.uberkitten.com"

    twitch_command_prefixes: list[str] = ["!", "¡", "?", "‽", "$", "~", "ඞ", "ꙮ"]

    # Target loudness for audio normalization (EBU R128)
    # Lower values are quieter
    # When changing, run: uv run python -m soundbot.cli regenerate-audio
    audio_target_lufs: float = -20.0


# Type checker doesn't understand that pydantic_settings loads from env
settings = Settings()  # type: ignore[call-arg]
