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

# Run locally (stop Docker first — state file lock prevents concurrent instances)
# docker compose stop
uv run python -m soundbot      # Start bot + web server
npm run dev                     # Frontend watch mode (separate terminal)

# CLI tools (subcommands: clip, regenerate-audio, check-sounds)
uv run python -m soundbot.cli                            # show help
uv run python -m soundbot.cli clip VIDEO NAME START END  # clip from a local video
uv run python -m soundbot.cli regenerate-audio           # re-normalize after LUFS change
uv run python -m soundbot.cli check-sounds               # find sounds with missing files

# Docker
docker-compose up --build

# Type checking
uv run pyright                  # Strict Pyright config in pyproject.toml
```

No test suite exists. Test manually: web UI at `http://localhost:8080`, Discord commands in a test guild.

## Development vs Production

The dev instance and Docker production container share the same state file and sounds directory via bind mount. A file lock (`config/state.lock`) prevents multiple instances from running simultaneously.

- **Dev workflow**: Stop Docker first (`docker compose stop`), then run locally. Restart Docker after with `docker compose up -d`.
- **Deploy**: `git push && docker compose build && docker compose up -d`

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

The web API has two tiers:
- **Public (unauthenticated)**: read-only browsing/playback. Public endpoints must stay **read-only** (GET only, plus the play-count POSTs).
- **Admin (`/api/admin/*`)**: mutations (add/trim/rename/delete/redownload) behind Discord OAuth. `require_admin` (`web/dependencies.py`) verifies a signed session cookie + membership in any guild the bot is in (10-min TTL cache). Auth routes live in `web/routes/auth.py`; configured via `DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`/`SESSION_SECRET` (unset → auth endpoints 503, app otherwise works).
- All mutations (Discord commands AND admin API) go through `sound_service` methods so WebSocket events + webhooks fire.
- Never expose tokens, internal state, or user data via API. Discord OAuth access tokens are used once (identify) and discarded; sessions are itsdangerous-signed cookies, no server-side session store.

## Discord Command Conventions

Every Discord command must follow these. Check new commands against this list.

**Surface:**
- Slash commands only. The single exception is the `!soundname` play listener in `PlaybackCog` — never add other text commands.
- `@app_commands.guild_only()` on any command needing a guild (all playback/voice). No manual `if not interaction.guild` checks.

**Name handling:**
- Apply `strip_command_prefix()` to every user-supplied sound/group name (and search queries) before use.
- **Edit/destructive commands** (delete, rename, trim, adjust, volume, redownload, alias, group membership) resolve names **exactly** via `resolve_sound_name` — exact name or alias only, never fuzzy auto-pick. On miss, suggest via `search_sounds`: `Did you mean: a, b, c?` — but never act on a guess.
- **Play commands** (play, playnext, playnow, loop, random, entrance/exit) resolve via `resolve_playable` (exact → alias → group random member → single partial match). Group names accepted wherever playable.

**Errors:**
- Error/validation replies are **ephemeral**; success replies are public. Ephemerality locks in at `defer()` time, so do all validation and name resolution *before* deferring. Post-defer failures (downloads, ffmpeg) stay as normal followups.
- Message shape: `❌ Sound '{name}' not found` / `❌ Sound or group '{name}' not found` (group-accepting commands), with the `Did you mean` tail when matches exist (≤5, ellipsis if more).
- Timestamp errors: `❌ Invalid start time: '{x}'. Use seconds (90) or MM:SS (1:30).`

**Inputs:**
- User-facing timestamps are strings parsed with `parse_timestamp` (accepts `90` and `1:30`) — never raw float parameters.

**Output:**
- Prefer **embeds** for informational/browse displays (info, search, list, queue, group list, alias list); plain one-liners with a status emoji for action confirmations.
- Emoji vocabulary: ✅ success · ❌ error · ℹ️ no-op · 🔊 sound/play · 🎲 random/groups · 🎵 play/queue · ⏭️ next/skip · ⏹️ stop · ⏸️ pause · ▶️ resume/playing · 🔁 loop · 📭 empty · 🚪 entrance/exit · 👋 leave. Embed colors: blue for sounds, purple for groups.
- Successful plays post one compact line via `post_clip_and_card` (`discord/cards.py`): `{emoji} [name](clip url) 🔗 [Source Title](<source url>)` — masked clip link unfurls the inline video player; no embed on play posts (an embed would suppress the unfurl). Falls back to a plain bold name when there's no video/clip.
- Anything that can exceed the 3s interaction window (downloads, transcodes) must `defer(thinking=True)` first.

**Side effects:**
- Play counting lives in the voice layer (`_play_next` → `record_discord_play`) — never count plays in command handlers. Each loop iteration counts.
- All mutations go through `sound_service` so WebSocket events + webhooks fire (see Security section).

## Key Patterns

- **Platform handling**: Windows uses `asyncio.run()`, Unix uses `uvloop.run()` — see `__main__.py`
- **Adding API endpoints**: Create handler in `web/routes/`, register in `web/routes/router.py`
- **Adding Discord slash commands**: Add to `SoundCommands` cog with `@app_commands.command()`
- **Adding Discord text commands**: Add to `PlaybackCog` with `@commands.command()`
- **Audio normalization**: Target is -20 LUFS (EBU R128)
- **Type checking**: Pyright strict mode — all new code must pass `pyright` cleanly
