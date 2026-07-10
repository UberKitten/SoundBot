from fastapi import APIRouter

from .admin import router as admin
from .auth import router as auth
from .clips import router as clips
from .drafts import router as drafts
from .index import router as index
from .settings import router as settings
from .sounds import router as sounds
from .ws import router as ws

router = APIRouter()

router.include_router(index)
router.include_router(settings)
router.include_router(sounds)
router.include_router(ws)
router.include_router(auth)
router.include_router(admin)
router.include_router(drafts)
router.include_router(clips)
