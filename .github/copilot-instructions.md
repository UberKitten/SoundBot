# SoundBot - Copilot Instructions

## Project Overview

SoundBot is a Discord soundboard bot with a web interface. Users can browse sounds on a web page and play them in Discord voice channels or copy links to share in chat.

## Tech Stack

### Backend (Python)
- **Python 3.14+** with **uv** for package management
- **FastAPI** - Web framework for the REST API
- **Hypercorn** - ASGI server
- **discord.py** - Discord bot library with voice support
- **Pydantic** - Data validation and settings management
- **Jinja2** - HTML templating
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
├── app.py              # Application startup (web + bot)
├── core/
│   ├── settings.py     # Pydantic settings from .env
│   └── state.py        # Runtime state management
├── discord/
│   ├── client.py       # Discord client and slash commands
│   └── commands/       # Command implementations
├── models/             # Pydantic models
├── services/           # Business logic layer
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

### Platform Compatibility
The app supports both Windows and Unix platforms:
- Windows uses standard `asyncio.run()`
- Unix uses `uvloop.run()` for better performance
- uvloop is an optional dependency (`uv sync --extra unix`)

## Common Tasks

### Adding a new API endpoint
1. Create route handler in `src/soundbot/web/routes/`
2. Register in `src/soundbot/web/routes/router.py`

### Adding a Discord command
1. Add command in `src/soundbot/discord/client.py` or create new file in `commands/`
2. Use `@soundbot_client.tree.command()` decorator

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
| `state_file` | No | Path to state JSON (default: `mount/state.json`) |
| `db_file` | No | Path to legacy DB JSON (default: `mount/db.json`) |
| `sounds_folder` | No | Path to sounds directory (default: `mount/sounds`) |

## Testing

When making changes:
1. Run locally with `uv run python -m soundbot`
2. Test web UI at `http://localhost:8080`
3. Test Discord commands in a test guild
