from pathlib import Path
from typing import Dict

import orjson
from pydantic import BaseModel

from app.core.settings import settings
from app.models.sounds import Sound


class State(BaseModel):
    entrances: Dict[str, str] = {}
    exits: Dict[str, str] = {}

    sounds: Dict[str, Sound] = {}

    def save(self):
        Path(settings.state_file).write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load():
        path = Path(settings.state_file)
        if path.exists():
            json_object = orjson.loads(path.read_text())
            return State(**json_object)
        else:
            return State()


# Don't actually use what we load from state, for now
State.load()
state = State()
# state = State.load()
