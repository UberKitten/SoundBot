import json
from pathlib import Path

from pydantic import BaseModel

from app.core.settings import settings


class State(BaseModel):
    token: None = None

    def save(self):
        Path(settings.state_file).write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load():
        path = Path(settings.state_file)
        if path.exists():
            json_object = json.loads(path.read_text())
            return State(**json_object)
        else:
            return State()


state = State.load()
