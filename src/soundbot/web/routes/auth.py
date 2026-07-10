import logging
import secrets
import time
from dataclasses import dataclass, field
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

# --- One-time login handoff store (iOS PWA cookie-jar split fix) ---
#
# iOS standalone PWAs open cross-origin navigations in an in-app Safari sheet
# with a DIFFERENT cookie jar than the PWA's webview, so the state cookie set
# by /api/auth/login never reaches the callback, and a session cookie set in
# the sheet never reaches the PWA. The handoff flow keeps OAuth state
# server-side and lets the PWA claim the resulting session afterwards:
#
#   POST /api/auth/handoff          -> {handoff_id, authorize_url}   (PWA)
#   GET  /api/auth/callback?state=<handoff_id>.<nonce>               (sheet)
#       validates against the store, completes login, stashes the
#       session payload in the entry (and sets a cookie in the sheet jar)
#   POST /api/auth/handoff/{id}/claim                                (PWA)
#       one-time: mints the session cookie in the PWA's jar
#
# Single process, in-memory only — entries are tiny and expire quickly.

HANDOFF_PENDING_TTL = 600  # 10 min to complete the OAuth dance
HANDOFF_CLAIM_TTL = 300  # 5 min to claim a completed login


@dataclass
class _HandoffEntry:
    state_nonce: str
    created: float = field(default_factory=time.monotonic)
    # Set by the callback on successful login: {"uid", "un", "av"}
    session_payload: Optional[dict[str, Optional[str]]] = None
    completed_at: Optional[float] = None
    claimed: bool = False


_handoffs: dict[str, _HandoffEntry] = {}


def _handoff_expired(entry: _HandoffEntry, now: float) -> bool:
    if entry.claimed:
        return True
    if entry.completed_at is not None:
        return (now - entry.completed_at) > HANDOFF_CLAIM_TTL
    return (now - entry.created) > HANDOFF_PENDING_TTL


def _gc_handoffs() -> None:
    """Opportunistically drop expired/claimed handoff entries."""
    now = time.monotonic()
    stale = [hid for hid, entry in _handoffs.items() if _handoff_expired(entry, now)]
    for hid in stale:
        del _handoffs[hid]


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


def _authorize_url(state: str) -> str:
    params = {
        "client_id": settings.discord_client_id,
        "response_type": "code",
        "scope": "identify",
        "redirect_uri": _redirect_uri(),
        "state": state,
    }
    return f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"


@router.get("/api/auth/login")
async def login() -> Response:
    """Redirect to Discord's OAuth2 authorize page (cookie-state flow)."""
    if not auth_configured():
        return ORJSONResponse(
            status_code=503, content={"detail": "Admin auth is not configured"}
        )

    state = secrets.token_urlsafe(32)
    response = RedirectResponse(url=_authorize_url(state), status_code=302)
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


@router.post("/api/auth/handoff")
async def create_handoff():
    """Start a cookie-less login handoff (for iOS PWAs with split cookie jars).

    Returns the Discord authorize URL with server-side state; the resulting
    session can be claimed exactly once via the claim endpoint.
    """
    if not auth_configured():
        return ORJSONResponse(
            status_code=503, content={"detail": "Admin auth is not configured"}
        )

    _gc_handoffs()
    handoff_id = secrets.token_urlsafe(32)
    state_nonce = secrets.token_urlsafe(32)
    _handoffs[handoff_id] = _HandoffEntry(state_nonce=state_nonce)
    return {
        "handoff_id": handoff_id,
        "authorize_url": _authorize_url(f"{handoff_id}.{state_nonce}"),
    }


@router.post("/api/auth/handoff/{handoff_id}/claim")
async def claim_handoff(handoff_id: str) -> Response:
    """One-time claim of a completed handoff login: mints the session cookie
    on THIS response (i.e. into the caller's cookie jar).

    202 while the OAuth dance is still pending; 404 for unknown, expired,
    or already-claimed handoffs. POST + unguessable id = CSRF-safe.
    """
    if not auth_configured():
        return ORJSONResponse(
            status_code=503, content={"detail": "Admin auth is not configured"}
        )

    _gc_handoffs()
    entry = _handoffs.get(handoff_id)
    if entry is None or entry.claimed:
        return ORJSONResponse(status_code=404, content={"detail": "Unknown handoff"})
    if entry.session_payload is None:
        return ORJSONResponse(status_code=202, content={"status": "pending"})

    entry.claimed = True
    del _handoffs[handoff_id]

    uid = entry.session_payload.get("uid")
    username = entry.session_payload.get("un")
    avatar = entry.session_payload.get("av")
    if not isinstance(uid, str) or not isinstance(username, str):
        # Shouldn't happen — the callback only stores validated values.
        return ORJSONResponse(status_code=404, content={"detail": "Unknown handoff"})

    user = AdminUser(id=uid, username=username, avatar=avatar)

    can_admin = False
    try:
        can_admin = await check_membership(user.id)
    except Exception as e:
        # Bot not ready or transient error — report authenticated but not admin.
        logger.debug(f"can_admin check failed in claim: {e}")

    response = ORJSONResponse(
        content={
            "authenticated": True,
            "can_admin": can_admin,
            "user": {
                "id": user.id,
                "username": user.username,
                "avatar_url": avatar_url(user.id, user.avatar),
            },
        }
    )
    make_session_cookie(response, user)
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

    if not code or not state:
        return fail("oauth_failed")

    # State is either "<handoff_id>.<nonce>" (server-side handoff flow) or a
    # plain nonce matched against the signed state cookie (legacy flow, kept
    # for single-jar browsers hitting /api/auth/login directly).
    _gc_handoffs()
    handoff_entry: Optional[_HandoffEntry] = None
    if "." in state:
        handoff_id, _, state_nonce = state.partition(".")
        candidate = _handoffs.get(handoff_id)
        if (
            candidate is not None
            # Each handoff completes at most once (no callback replays).
            and candidate.session_payload is None
            and secrets.compare_digest(state_nonce, candidate.state_nonce)
        ):
            handoff_entry = candidate
    if handoff_entry is None:
        # Legacy cookie-state validation.
        if not soundbot_oauth_state:
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

    if handoff_entry is not None:
        # Stash the session for the originating (PWA) jar to claim, and hint
        # the sheet-side page that it can be closed.
        handoff_entry.session_payload = {
            "uid": user_id,
            "un": username,
            "av": avatar_hash,
        }
        handoff_entry.completed_at = time.monotonic()
        redirect_to = "/?login_done=1"
    else:
        redirect_to = "/"

    # Always set the session cookie on this response too — single-jar
    # browsers are fully logged in with zero extra roundtrips.
    response = RedirectResponse(url=redirect_to, status_code=302)
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
