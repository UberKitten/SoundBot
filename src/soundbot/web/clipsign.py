"""HMAC signing for public clip URLs.

Legacy links sign canonical names exactly as before. New bounded links use the
short storage directory and a derived, domain-separated HMAC key so signatures
cannot be replayed across the two routes. Rotating SESSION_SECRET invalidates
both kinds of link.
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


def _compute_directory_sig(directory: str, exp: int) -> str:
    """Sign a storage identifier under a key distinct from legacy name links."""
    scoped_key = hmac.new(
        _secret(), b"soundbot:clip-directory:v1", hashlib.sha256
    ).digest()
    payload = f"{directory}:{exp}".encode()
    return hmac.new(scoped_key, payload, hashlib.sha256).hexdigest()


def sign_clip_url(name: str, expires_at: int) -> str:
    """Build a signed, relative clip URL for the canonical sound name.

    The path must end in ".mp4" — Discord only inline-embeds direct links
    whose path ends in the extension (query params after are fine).
    """
    sig = _compute_sig(name, expires_at)
    return f"/clips/{quote(name, safe='')}.mp4?exp={expires_at}&sig={sig}"


def verify_clip_sig(name: str, exp: int, sig: str) -> bool:
    """Constant-time check of a clip signature (does NOT check expiry)."""
    expected = _compute_sig(name, exp)
    return hmac.compare_digest(expected, sig)


def sign_clip_directory_url(directory: str, expires_at: int) -> str:
    """Build a bounded signed URL using the sound's short storage directory."""
    sig = _compute_directory_sig(directory, expires_at)
    identifier = quote(directory, safe="")
    return f"/clip-ids/{identifier}.mp4?exp={expires_at}&sig={sig}"


def verify_clip_directory_sig(directory: str, exp: int, sig: str) -> bool:
    """Check a storage-directory signature without accepting legacy signatures."""
    expected = _compute_directory_sig(directory, exp)
    return hmac.compare_digest(expected, sig)


def build_clip_share_url(name: str, now: Optional[int] = None) -> str:
    """Absolute signed clip URL for sharing (Discord /clip, OBS, etc.).

    Expires CLIP_LINK_TTL_SECONDS (180 days) after `now`. The base URL is
    the same one OAuth redirects use (OAUTH_REDIRECT_BASE override, else
    https://{WEB_UI_URL}).
    """
    expires_at = (now if now is not None else int(time.time())) + CLIP_LINK_TTL_SECONDS
    return f"{public_base_url()}{sign_clip_url(name, expires_at)}"


def build_clip_directory_share_url(
    directory: str, now: Optional[int] = None
) -> str:
    """Absolute signed clip URL whose path stays bounded for long sound names."""
    expires_at = (now if now is not None else int(time.time())) + CLIP_LINK_TTL_SECONDS
    return f"{public_base_url()}{sign_clip_directory_url(directory, expires_at)}"
