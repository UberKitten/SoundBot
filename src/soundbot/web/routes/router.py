from fastapi import APIRouter

from .index import router as index
from .settings import router as settings
from .sounds import router as sounds

router = APIRouter()

router.include_router(index)
router.include_router(settings)
router.include_router(sounds)
