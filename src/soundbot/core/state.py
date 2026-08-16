import atexit
import fcntl
import logging
import sys
from pathlib import Path

import orjson

from soundbot.core.settings import settings
from soundbot.models.state import StateDocument, atomic_write_json

logger = logging.getLogger(__name__)

# File lock to prevent multiple instances from corrupting state
_lock_file = None


def _acquire_lock():
    """Acquire an exclusive lock on state.json.lock to prevent multiple instances."""
    global _lock_file
    lock_path = Path(settings.state_file).with_suffix(".lock")
    _lock_file = open(lock_path, "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.write(str(Path("/proc/self").resolve()))
        _lock_file.flush()
    except OSError:
        logger.critical(
            "Another SoundBot instance is already running (could not acquire lock on %s). Kill the other process first.",
            lock_path,
        )
        sys.exit(1)


def _release_lock():
    """Release the state lock."""
    global _lock_file
    if _lock_file:
        try:
            fcntl.flock(_lock_file, fcntl.LOCK_UN)
            _lock_file.close()
        except Exception:
            pass
        _lock_file = None


class State(StateDocument):
    def save(self):
        atomic_write_json(
            Path(settings.state_file),
            self.model_dump(mode="json"),
        )

    @staticmethod
    def load():
        path = Path(settings.state_file)
        if path.exists():
            json_object = orjson.loads(path.read_text())
            return State(**json_object)
        return State()


# Acquire lock before loading state
_acquire_lock()
atexit.register(_release_lock)

# Load state from state.json
state = State.load()
