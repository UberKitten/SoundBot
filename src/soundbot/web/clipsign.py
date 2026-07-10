"""HMAC signing for public clip URLs.

Signed links let Discord / OBS hotlink a sound's browser clip without any
cookie auth — the signature IS the auth. HMAC-SHA256 over "{name}:{exp}"
keyed by settings.session_secret; rotating SESSION_SECRET invalidates every
previously issued link.
"""

import hashlib
import hmac
import time
from typing import Optional
from urllib.parse import quote

from fastapi import HTTPException

from soundbot.core.settings import settings
from soundbot.web.urls import public_base_url

# How long a shared clip link stays valid (e.g. from the /clip command).
CLIP_LINK_TTL_SECONDS = 180 * 24 * 60 * 60  # 180 days


def _secret() -> bytes:
    """The signing key. 503 when SESSION_SECRET is unset."""
    if not settings.session_secret:
        raise HTTPException(
            status_code=503, detail="Clip links are not configured (no session secret)"
        )
    return settings.session_secret.encode()


def _compute_sig(name: str, exp: int) -> str:
    payload = f"{name}:{exp}".encode()
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def sign_clip_url(name: str, expires_at: int) -> str:
    """Build a signed, relative clip URL for the canonical sound name.

    The path must end in ".mp4" — Discord only inline-embeds direct links
    whose path ends in the extension (query params after are fine).
    """
    sig = _compute_sig(name, expires_at)
    return f"/clips/{quote(name)}.mp4?exp={expires_at}&sig={sig}"


def verify_clip_sig(name: str, exp: int, sig: str) -> bool:
    """Constant-time check of a clip signature (does NOT check expiry)."""
    expected = _compute_sig(name, exp)
    return hmac.compare_digest(expected, sig)


def build_clip_share_url(name: str, now: Optional[int] = None) -> str:
    """Absolute signed clip URL for sharing (Discord /clip, OBS, etc.).

    Expires CLIP_LINK_TTL_SECONDS (180 days) after `now`. The base URL is
    the same one OAuth redirects use (OAUTH_REDIRECT_BASE override, else
    https://{WEB_UI_URL}).
    """
    expires_at = (now if now is not None else int(time.time())) + CLIP_LINK_TTL_SECONDS
    return f"{public_base_url()}{sign_clip_url(name, expires_at)}"
