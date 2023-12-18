from typing import Dict, List, Optional

from pydantic import BaseModel


class OldSound(BaseModel):
    name: str
    filename: Optional[str] = None
    modified: Optional[int] = None
    count: int = 0
    tags: List[str] = []


class OldDB(BaseModel):
    entrances: Dict[str, str]
    exits: Dict[str, str]
    sounds: List[OldSound]
    ignoreList: List[str]
