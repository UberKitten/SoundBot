from typing import Dict, Optional, List
from pydantic import BaseModel

class Sound(BaseModel):
    name: str
    filename: Optional[str]
    modified: Optional[int]
    count: int = 0
    tags: List[str] = []

class DB(BaseModel):
    entrances: Dict[str,str]
    exits: Dict[str,str]
    sounds: List[Sound]
    ignoreList: List[str]
