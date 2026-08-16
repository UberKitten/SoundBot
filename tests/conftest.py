"""Pytest configuration and shared fixtures.

Hermeticity is enforced at import time: BEFORE any ``soundbot`` module is
imported, we redirect the settings singleton at a throwaway temp directory
via environment variables. This matters because:

- ``soundbot.core.settings.Settings`` requires ``TOKEN`` and would otherwise
  read the real ``.env``.
- ``soundbot.core.state`` acquires an exclusive file lock on ``STATE_FILE``
  and ``sys.exit(1)``s if it can't (the Docker instance holds the real lock),
  then loads state from that path.

Pointing ``STATE_FILE`` / ``SOUNDS_FOLDER`` at a per-session temp dir means the
tests neither read nor write the real ``config/`` or ``sounds/`` directories,
and never contend with the running bot's lock.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# --- Isolate settings/state BEFORE importing any soundbot module ---
_TMP_ROOT = tempfile.mkdtemp(prefix="soundbot_tests_")
_ = os.environ.setdefault("TOKEN", "test-token-not-real")
os.environ["STATE_FILE"] = str(Path(_TMP_ROOT) / "state.json")
os.environ["SOUNDS_FOLDER"] = str(Path(_TMP_ROOT) / "sounds")
# Prevent pydantic-settings from reading a stray real .env for other keys.
_ = os.environ.setdefault("API_KEY", "")

# These imports MUST come after the env setup above.
from soundbot.core.state import state  # noqa: E402
from soundbot.models.sounds import Sound, SoundFiles  # noqa: E402
from soundbot.services.sounds import sound_service  # noqa: E402


def make_sound(directory: str = "snd", **overrides: object) -> Sound:
    """Build a minimal valid Sound for state-level tests.

    Only the fields the service logic touches need to be real; file paths are
    nominal because these tests never hit ffmpeg or the filesystem.
    """
    files = SoundFiles(
        original=f"{directory}_original.mkv",
        trimmed_audio=f"{directory}.ogg",
    )
    return Sound(  # type: ignore[arg-type]
        directory=directory,
        files=files,
        **{"duration": 1.0, **overrides},
    )


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    """Reset the global state + service caches between tests.

    ``state`` and ``sound_service`` are module-level singletons; without this
    every test would see leftover sounds/groups from prior tests.
    """
    state.sounds.clear()
    state.groups.clear()
    state.entrances.clear()
    state.exits.clear()
    sound_service._group_shuffle_bags.clear()
    yield
    state.sounds.clear()
    state.groups.clear()
    state.entrances.clear()
    state.exits.clear()
    sound_service._group_shuffle_bags.clear()
