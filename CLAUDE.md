# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SoundBot is a Discord soundboard bot with a web interface. Users browse/play sounds via a web UI or Discord commands. Sounds are downloaded from URLs (via yt-dlp), processed with FFmpeg, and played in Discord voice channels.

## Commands

```bash
# Install dependencies
uv sync                        # Python deps
uv sync --extra unix           # Include uvloop (Linux/macOS only)
npm ci && npm run build        # Frontend (TypeScript/CSS via Gulp)

# Run (web only — default for dev, avoids conflicting with production Discord bot)
uv run python -m soundbot --web-only
npm run dev                     # Frontend watch mode (separate terminal)

# Run (full — only when working on Discord commands; stop Docker container first)
# docker compose stop
uv run python -m soundbot

# CLI tools
uv run python -m soundbot.cli  # CLI utilities (check sounds, regenerate audio)

# Docker
docker-compose up --build

# Type checking
uv run pyright                  # Strict Pyright config in pyproject.toml
```

No test suite exists. Test manually: web UI at `http://localhost:8080`, Discord commands in a test guild.

## Development vs Production

The dev instance and Docker production container share the same state file and sounds directory. To avoid two Discord bot instances conflicting:

- **Default dev workflow**: Use `--web-only` flag (web server only, no Discord bot)
- **Full testing** (Discord commands): Stop Docker first with `docker compose stop`, then run without `--web-only`. Restart Docker after with `docker compose up -d`.

## Architecture

The app runs two concurrent services in one process: a **FastAPI web server** (Hypercorn on port 8080) and a **Discord bot** (discord.py).

### Backend layers

- **`core/settings.py`** — Pydantic settings singleton loaded from `.env`. Access via `from soundbot.core.settings import settings`.
- **`core/state.py`** — Runtime state (sounds dict, user prefs) persisted to `config/state.json`. Access via `from soundbot.core.state import state`. Call `state.save()` after mutations.
- **`services/`** — Business logic singletons: `sound_service`, `voice_service`, `ytdlp_service`, `ffmpeg_service`, `webhook_service`. These are the main API for all operations.
- **`discord/client.py`** — Discord bot with cogs: `SoundCommands` (slash), `PlaybackCog` (text: `!soundname`), `QueueCog`, `UserSettingsCog`, `VoiceEventsCog`.
- **`web/`** — FastAPI app with routes in `web/routes/`, WebSocket at `/api/ws` for real-time UI updates.

### Frontend

Vanilla TypeScript compiled with Gulp to `web/dist/` (cache-busted with gulp-rev). Key files in `web/scripts/`: `soundboard-app.ts` (main), `websocket.ts` (live updates), `audio.ts` (preview playback).

### Sound storage

Each sound gets a directory under `sounds/<name>/` containing: original download, processed `.ogg` (for Discord playback), trimmed video (if applicable), and yt-dlp `metadata.json`.

## Security

The web API is **public and unauthenticated**:
- API endpoints must be **read-only** (GET only)
- All mutations go through Discord commands, never the web API
- Never expose tokens, internal state, or user data via API

## Key Patterns

- **Platform handling**: Windows uses `asyncio.run()`, Unix uses `uvloop.run()` — see `__main__.py`
- **Adding API endpoints**: Create handler in `web/routes/`, register in `web/routes/router.py`
- **Adding Discord slash commands**: Add to `SoundCommands` cog with `@app_commands.command()`
- **Adding Discord text commands**: Add to `PlaybackCog` with `@commands.command()`
- **Audio normalization**: Target is -20 LUFS (EBU R128)
- **Type checking**: Pyright strict mode — all new code must pass `pyright` cleanly
