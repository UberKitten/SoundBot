import logging
import time
from dataclasses import dataclass
from typing import Optional

import discord
from fastapi import Cookie, HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from soundbot.core.settings import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()

# Session cookie config
SESSION_COOKIE_NAME = "soundbot_session"
STATE_COOKIE_NAME = "soundbot_oauth_state"
STATE_MAX_AGE = 600  # 10 minutes for the OAuth state cookie

# Membership verdict cache: uid -> (is_member, checked_at_monotonic)
_MEMBERSHIP_TTL = 600  # 10 minutes
_membership_cache: dict[str, tuple[bool, float]] = {}


@dataclass
class AdminUser:
    """Authenticated admin user resolved from a valid session cookie."""

    id: str
    username: str
    avatar: Optional[str]


def _serializer() -> URLSafeTimedSerializer:
    """Build the signed-cookie serializer. Requires session_secret to be set."""
    if not settings.session_secret:
        raise HTTPException(status_code=503, detail="Auth is not configured")
    return URLSafeTimedSerializer(settings.session_secret, salt="soundbot-session")


def auth_configured() -> bool:
    """True when Discord OAuth admin auth is fully configured."""
    return bool(
        settings.discord_client_id
        and settings.discord_client_secret
        and settings.session_secret
    )


def make_session_cookie(response: Response, user: AdminUser) -> None:
    """Sign the user into a session cookie on the given response."""
    serializer = _serializer()
    payload = {"uid": user.id, "un": user.username, "av": user.avatar}
    token = serializer.dumps(payload)
    max_age = settings.admin_session_days * 24 * 60 * 60
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def read_session(token: Optional[str]) -> Optional[AdminUser]:
    """Decode + verify a session cookie value into an AdminUser, or None."""
    if not token or not settings.session_secret:
        return None
    serializer = _serializer()
    max_age = settings.admin_session_days * 24 * 60 * 60
    try:
        data = serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    username = data.get("un")
    avatar = data.get("av")
    if not isinstance(uid, str) or not isinstance(username, str):
        return None
    if avatar is not None and not isinstance(avatar, str):
        avatar = None
    return AdminUser(id=uid, username=username, avatar=avatar)


async def check_membership(user_id: str) -> bool:
    """Return True if user_id is a member of ANY guild the bot is in.

    Verdicts are cached for 10 minutes to avoid hammering the Discord API.
    Raises HTTPException(503) if the bot is not ready.

    The `members` privileged intent is not enabled, so the member cache may
    miss; we fall back to fetch_member (a REST call) on a cache miss.
    """
    # Import here to avoid pulling the discord bot into the web import graph
    # at module import time.
    from soundbot.discord.client import soundbot_client

    now = time.monotonic()
    cached = _membership_cache.get(user_id)
    if cached is not None and (now - cached[1]) < _MEMBERSHIP_TTL:
        return cached[0]

    if not soundbot_client.is_ready():
        raise HTTPException(
            status_code=503, detail="Discord bot is not ready; try again shortly"
        )

    try:
        uid_int = int(user_id)
    except ValueError:
        _membership_cache[user_id] = (False, now)
        return False

    is_member = False
    for guild in soundbot_client.guilds:
        member = guild.get_member(uid_int)
        if member is not None:
            is_member = True
            break
        # Cache miss (members intent disabled) — fall back to a REST fetch.
        try:
            _ = await guild.fetch_member(uid_int)
            is_member = True
            break
        except discord.NotFound:
            continue
        except discord.HTTPException as e:
            logger.warning(f"fetch_member failed for {uid_int} in {guild.id}: {e}")
            continue

    _membership_cache[user_id] = (is_member, now)
    return is_member


async def no_cache(response: Response):
    response.headers['cache-control'] = 'no-store'


async def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="API key not configured")
    if credentials.credentials != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def require_admin(
    soundbot_session: Optional[str] = Cookie(default=None),
) -> AdminUser:
    """FastAPI dependency: require a valid session + guild membership."""
    if not auth_configured():
        raise HTTPException(status_code=503, detail="Admin auth is not configured")

    user = read_session(soundbot_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not await check_membership(user.id):
        raise HTTPException(
            status_code=403, detail="You are not a member of an authorized server"
        )

    return user
