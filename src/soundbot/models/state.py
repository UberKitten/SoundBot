import os
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict

import orjson
from pydantic import BaseModel, model_validator

from soundbot.models.sounds import Sound, SoundGroupData


class StateDocument(BaseModel):
    """Validated persisted SoundBot state without runtime lock side effects."""

    entrances: Dict[str, str] = {}
    exits: Dict[str, str] = {}
    sounds: Dict[str, Sound] = {}
    groups: Dict[str, SoundGroupData] = {}

    @model_validator(mode="before")
    @classmethod
    def migrate_groups(cls, data: Any) -> Any:
        """Migrate groups from old list[str] format to SoundGroupData."""
        if isinstance(data, dict) and "groups" in data:
            groups = data["groups"]
            for name, value in groups.items():
                if isinstance(value, list):
                    groups[name] = {"members": value}
        return data

    @model_validator(mode="after")
    def require_unique_playable_paths(self):
        owners: dict[str, str] = {}
        for name, sound in self.sounds.items():
            path = str(PurePosixPath(sound.directory) / sound.files.trimmed_audio)
            previous = owners.get(path)
            if previous is not None:
                raise ValueError(
                    f"Sounds '{previous}' and '{name}' share playable OGG path '{path}'"
                )
            owners[path] = name
        return self


def atomic_write_json(path: Path, document: object) -> None:
    """Durably replace a JSON document with one same-directory atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    payload = orjson.dumps(document, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, existing_mode)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            _ = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)
