from fastapi import APIRouter

from .index import router as index
from .settings import router as settings
from .sounds import router as sounds
from .ws import router as ws

router = APIRouter()

router.include_router(index)
router.include_router(settings)
router.include_router(sounds)
router.include_router(ws)
