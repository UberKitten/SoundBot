import logging
import secrets
from typing import Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import APIRouter, Cookie, Response
from fastapi.responses import ORJSONResponse, RedirectResponse

from soundbot.core.settings import settings
from soundbot.web.dependencies import (
    STATE_COOKIE_NAME,
    STATE_MAX_AGE,
    AdminUser,
    auth_configured,
    check_membership,
    clear_session_cookie,
    make_session_cookie,
    read_session,
)
from soundbot.web.urls import public_base_url

logger = logging.getLogger(__name__)
router = APIRouter()

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"


def _redirect_uri() -> str:
    return f"{public_base_url()}/api/auth/callback"


def avatar_url(user_id: str, avatar_hash: Optional[str]) -> str:
    """Build a CDN avatar URL, falling back to the default embed avatar."""
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
    # Default embed avatar (new username system uses (id >> 22) % 6)
    try:
        index = (int(user_id) >> 22) % 6
    except ValueError:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


@router.get("/api/auth/login")
async def login() -> Response:
    """Redirect to Discord's OAuth2 authorize page."""
    if not auth_configured():
        return ORJSONResponse(
            status_code=503, content={"detail": "Admin auth is not configured"}
        )

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.discord_client_id,
        "response_type": "code",
        "scope": "identify",
        "redirect_uri": _redirect_uri(),
        "state": state,
    }
    url = f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"

    response = RedirectResponse(url=url, status_code=302)
    # Short-lived signed state cookie to defend against CSRF.
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )
    return response


@router.get("/api/auth/callback")
async def callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    soundbot_oauth_state: Optional[str] = Cookie(default=None),
) -> Response:
    """Handle the OAuth2 redirect: exchange code, verify user + membership."""
    if not auth_configured():
        return ORJSONResponse(
            status_code=503, content={"detail": "Admin auth is not configured"}
        )

    def fail(reason: str) -> RedirectResponse:
        resp = RedirectResponse(url=f"/?login_error={reason}", status_code=302)
        resp.delete_cookie(key=STATE_COOKIE_NAME, path="/")
        return resp

    # Verify the state parameter against the signed cookie.
    if not code or not state or not soundbot_oauth_state:
        return fail("oauth_failed")
    if not secrets.compare_digest(state, soundbot_oauth_state):
        return fail("oauth_failed")

    redirect_uri = _redirect_uri()
    token_data = {
        "client_id": settings.discord_client_id,
        "client_secret": settings.discord_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DISCORD_TOKEN_URL,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as token_resp:
                if token_resp.status != 200:
                    body = await token_resp.text()
                    logger.warning(
                        f"Discord token exchange failed ({token_resp.status}): {body}"
                    )
                    return fail("oauth_failed")
                token_json = await token_resp.json()

            access_token = token_json.get("access_token")
            if not access_token:
                return fail("oauth_failed")

            async with session.get(
                DISCORD_USER_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as user_resp:
                if user_resp.status != 200:
                    return fail("oauth_failed")
                user_json = await user_resp.json()
    except aiohttp.ClientError as e:
        logger.warning(f"Discord OAuth HTTP error: {e}")
        return fail("oauth_failed")

    user_id = user_json.get("id")
    if not isinstance(user_id, str):
        return fail("oauth_failed")
    # Prefer global_name, then username, for display.
    username = (
        user_json.get("global_name")
        or user_json.get("username")
        or "unknown"
    )
    avatar_hash = user_json.get("avatar")

    # We only need identify scope; the access token is discarded here.
    try:
        is_member = await check_membership(user_id)
    except Exception as e:
        logger.warning(f"Membership check failed during callback: {e}")
        return fail("oauth_failed")

    if not is_member:
        return fail("not_a_member")

    admin_user = AdminUser(id=user_id, username=username, avatar=avatar_hash)
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key=STATE_COOKIE_NAME, path="/")
    make_session_cookie(response, admin_user)
    return response


@router.post("/api/auth/logout", status_code=204)
async def logout() -> Response:
    """Clear the session cookie."""
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/api/auth/me")
async def me(soundbot_session: Optional[str] = Cookie(default=None)):
    """Return the current auth status. Always 200."""
    user = read_session(soundbot_session)
    if user is None:
        return {"authenticated": False, "can_admin": False, "user": None}

    can_admin = False
    try:
        can_admin = await check_membership(user.id)
    except Exception as e:
        # Bot not ready or transient error — report authenticated but not admin.
        logger.debug(f"can_admin check failed in /me: {e}")

    return {
        "authenticated": True,
        "can_admin": can_admin,
        "user": {
            "id": user.id,
            "username": user.username,
            "avatar_url": avatar_url(user.id, user.avatar),
        },
    }
