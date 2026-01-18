# SoundBot

A Discord soundboard bot with a web interface. Browse and search sounds on a web page, then play them in Discord voice channels or copy links to paste in chat.

## Features

- **Web Interface**: Browse, search, and preview sounds from a responsive web UI
- **Discord Integration**: Play sounds in voice channels via slash commands
- **Sound Management**: Add sounds from URLs (supports any site yt-dlp can download from)

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [FFmpeg](https://ffmpeg.org/) (for audio processing)
- Node.js 24+ (for building web assets)
- A Discord bot token

## Quick Start

### 1. Install dependencies

```bash
# Install Python dependencies
uv sync

# On Linux/macOS, include uvloop for better async performance
uv sync --extra unix

# Install Node.js dependencies and build web assets
npm ci
npm run build
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
# Required: Discord bot token
token=your_discord_bot_token_here

# Optional: Comma-separated guild IDs for local command registration
test_guild_ids=123456789,987654321

# Optional: Override default paths
# state_file=mount/state.json
# db_file=mount/db.json
# sounds_folder=mount/sounds
# static_folder=web/dist
# templates_folder=web/template
```

### 3. Create mount directories

```bash
mkdir -p mount/sounds
```

### 4. Run the bot

```bash
uv run python -m soundbot
```

The web interface will be available at `http://localhost:8080`.

## Docker

### Using Docker Compose

1. Copy `.env.example` to `.env` and configure your settings
2. Run:

```bash
docker-compose up --build
```

### Environment Variables for Docker

| Variable | Description |
|----------|-------------|
| `token` | Discord bot token (required) |
| `test_guild_ids` | Comma-separated guild IDs for command registration |
| `SOUNDBOT_PORT_8080` | Host port to map to container port 8080 |
| `DOCKERCONFDIR` | Base path for config/data volumes |

## Project Structure

```
├── src/soundbot/          # Python backend
│   ├── core/              # Settings and state management
│   ├── discord/           # Discord bot client and commands
│   ├── models/            # Data models
│   ├── services/          # Business logic
│   └── web/               # FastAPI web server and routes
├── web/                   # Frontend assets
│   ├── scripts/           # TypeScript source
│   ├── styles/            # CSS
│   ├── static/            # Static assets
│   └── template/          # Jinja2 templates
├── mount/                 # Runtime data (sounds, state)
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Development

### Running locally

```bash
# Install all dependencies
uv sync
npm ci

# Build web assets
npm run build

# Run the bot (serves web UI at http://localhost:8080)
uv run python -m soundbot
```

### Watch mode for frontend development

Run these in separate terminals:

```bash
# Terminal 1: Watch and rebuild CSS/TypeScript on changes
npm run dev

# Terminal 2: Run the Python backend
uv run python -m soundbot
```

### Platform Notes

- **Windows**: Uses standard `asyncio` event loop
- **Linux/macOS**: Uses `uvloop` for improved async performance (install with `uv sync --extra unix`)

## Discord Commands

| Command | Description |
|---------|-------------|
| `/play <name>` | Play a sound in voice channel |
| `/add <name> <url>` | Add a sound from a URL |

## License

MIT
