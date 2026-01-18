"""API routes for application settings."""

from fastapi import APIRouter

from soundbot.core.settings import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/prefixes")
async def get_command_prefixes():
    """Get the list of command prefixes for the soundboard."""
    return {
        "prefixes": settings.twitch_command_prefixes or ["!"],
    }


@router.get("")
async def get_public_settings():
    """Get public settings (non-sensitive configuration)."""
    return {
        "command_prefixes": settings.twitch_command_prefixes or ["!"],
    }
