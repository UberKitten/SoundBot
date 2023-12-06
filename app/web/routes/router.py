from fastapi import APIRouter

from .db import router as db
from .index import router as index
from .sounds import router as sounds

router = APIRouter()

router.include_router(db)
router.include_router(index)
router.include_router(sounds)
