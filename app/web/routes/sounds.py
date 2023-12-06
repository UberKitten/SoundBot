import logging

from fastapi import APIRouter, Depends

from app.core.state import state
from app.web.dependencies import no_cache

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/sounds", dependencies=[Depends(no_cache)])
async def get_sounds():
    return state.sounds
