"""Public URL helpers shared by OAuth redirects and clip links."""

from soundbot.core.settings import settings


def public_base_url() -> str:
    """The site's public base URL (no trailing slash).

    Prefers the explicit OAUTH_REDIRECT_BASE override, else derives
    https://{WEB_UI_URL} — the same logic OAuth redirects use.
    """
    if settings.oauth_redirect_base:
        return settings.oauth_redirect_base.rstrip("/")
    return f"https://{settings.web_ui_url}"
