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

    # Title shown in the browser tab, PWA app name, and OpenAPI docs.
    app_title: str = "Soundboard"
    # Short name for PWA installs (recommended max 12 chars). Falls back to app_title.
    app_short_title: Optional[str] = None

    twitch_command_prefixes: list[str] = ["!", "¡", "?", "‽", "$", "~", "ඞ", "ꙮ"]

    # API key for authenticated endpoints (stream play recording)
    api_key: Optional[str] = None

    # Target loudness for audio normalization (EBU R128)
    # Lower values are quieter
    # When changing, run: uv run python -m soundbot.cli regenerate-audio
    audio_target_lufs: float = -20.0

    # --- Discord OAuth admin auth (all optional) ---
    # When these are unset, auth endpoints return 503 and the site stays
    # anonymous/read-only. Set client id/secret + session secret to enable
    # admin login via Discord OAuth.
    discord_client_id: Optional[str] = None
    discord_client_secret: Optional[str] = None
    # Long random string used to sign session cookies (e.g. `openssl rand -hex 32`)
    session_secret: Optional[str] = None
    # Base URL for OAuth redirects. If None, derived as https://{web_ui_url}.
    # The OAuth2 redirect URI registered in the Discord portal must be
    # "{oauth_redirect_base}/api/auth/callback".
    oauth_redirect_base: Optional[str] = None
    # How long an admin session cookie stays valid.
    admin_session_days: int = 30


# Type checker doesn't understand that pydantic_settings loads from env
settings = Settings()  # type: ignore[call-arg]
