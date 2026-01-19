# SoundBot - Copilot Instructions

## Project Overview

SoundBot is a Discord soundboard bot with a web interface. Users can browse sounds on a web page and play them in Discord voice channels or copy links to share in chat.

## Security

The web API is **public and unauthenticated**. When adding or modifying API endpoints:
- **Never** expose sensitive information (tokens, internal state, user data)
- **Never** allow API methods to modify data (all mutations should go through Discord commands)
- API endpoints should be read-only and return only public sound metadata

## Tech Stack

### Backend (Python)
- **Python 3.14+** with **uv** for package management
- **FastAPI** - Web framework for the REST API
- **Hypercorn** - ASGI server
- **discord.py** - Discord bot library with voice support
- **Pydantic** - Data validation and settings management
- **Jinja2** - HTML templating
- **yt-dlp** - Video/audio downloading
- **FFmpeg** - Audio processing and normalization
- **uvloop** - Fast event loop (Linux/macOS only)

### Frontend (TypeScript)
- **TypeScript** compiled with Gulp
- Vanilla JS with custom components
- CSS for styling

### Infrastructure
- **Docker** with multi-stage builds
- **docker-compose** for deployment

## Project Structure

```
src/soundbot/           # Main Python package
├── __main__.py         # Entry point - handles platform-specific event loop
├── app.py              # Application startup (web + bot + yt-dlp updater)
├── core/
│   ├── settings.py     # Pydantic settings from .env
│   └── state.py        # Runtime state management
├── discord/
│   ├── client.py       # Discord bot with slash commands and text commands
│   └── commands/       # Additional command modules
├── models/
│   └── sounds.py       # Sound, Timestamps, Stats models
├── services/
│   ├── sounds.py       # Sound CRUD operations
│   ├── ytdlp.py        # yt-dlp download and metadata
│   ├── ffmpeg.py       # Audio processing and normalization
│   └── voice.py        # Voice channel management and playback
└── web/
    ├── web.py          # FastAPI app factory
    ├── routes/         # API route handlers
    ├── dependencies.py # FastAPI dependencies
    └── models.py       # Request/response models

web/                    # Frontend source
├── scripts/            # TypeScript source files
├── styles/             # CSS stylesheets
├── static/             # Static assets (icons, manifests)
└── template/           # Jinja2 HTML templates

config/sounds/           # Sound storage
└── <sound_name>/       # Each sound has its own directory
    ├── metadata.json   # yt-dlp metadata
    ├── <name>.mkv      # Original downloaded file
    ├── <name>.ogg      # Processed audio for Discord
    └── <name>_trimmed.mkv  # Trimmed video (if applicable)
```

## Key Patterns

### Settings
All configuration is loaded from environment variables or `.env` file via Pydantic:
```python
from soundbot.core.settings import settings
settings.token  # Discord bot token
settings.sounds_folder  # Path to sounds directory
```

### State Management
Runtime state (sounds, user preferences) is managed via a singleton:
```python
from soundbot.core.state import state
state.sounds["name"]  # Access sound data
state.save()  # Persist to disk
```

### Services
Business logic is organized into services:
```python
from soundbot.services.sounds import sound_service
from soundbot.services.voice import voice_service
from soundbot.services.ytdlp import ytdlp_service
from soundbot.services.ffmpeg import ffmpeg_service

# Add a sound from URL
await sound_service.add_sound("name", "https://youtube.com/...", start=5, end=10)

# Play in voice channel
await voice_service.play_sound(guild, audio_path, user=member)
```

### Platform Compatibility
The app supports both Windows and Unix platforms:
- Windows uses standard `asyncio.run()`
- Unix uses `uvloop.run()` for better performance
- uvloop is an optional dependency (`uv sync --extra unix`)

## Common Tasks

### Adding a new API endpoint
1. Create route handler in `src/soundbot/web/routes/`
2. Register in `src/soundbot/web/routes/router.py`

### Adding a Discord slash command
1. Add to `SoundCommands` cog in `src/soundbot/discord/client.py`
2. Use `@app_commands.command()` decorator

### Adding a Discord text command
1. Add to `PlaybackCog` in `src/soundbot/discord/client.py`
2. Use `@commands.command()` decorator

### Modifying the web UI
1. Edit TypeScript in `web/scripts/`
2. Edit CSS in `web/styles/`
3. Rebuild with `npm run build`

## Running the Project

```bash
# Development
uv sync
npm ci && npm run build
uv run python -m soundbot

# Docker
docker-compose up --build
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `token` | Yes | Discord bot token |
| `test_guild_ids` | No | Comma-separated guild IDs for slash command registration |
| `state_file` | No | Path to state JSON (default: `config/state.json`) |
| `sounds_folder` | No | Path to sounds directory (default: `config/sounds`) |

## Testing

When making changes:
1. Run locally with `uv run python -m soundbot`
2. Test web UI at `http://localhost:8080`
3. Test Discord commands in a test guild
