# SoundBot

A Discord soundboard bot with a web interface. Browse and search sounds on a web page, then play them in Discord voice channels or copy links to paste in chat.

## Features

- **Web Interface**: Browse, search, and preview sounds from a responsive web UI
- **Group previews**: Click a group to play a shuffled member; click it again while loading or playing to stop. Stopping does not advance the shuffle or record another play. A group's highlight and progress belong to that exact preview request and clear when another sound or group replaces it, even when both select the same member.
- **Group clips**: Authenticated group previews, including shared group links, automatically open the selected member's clip and retarget the existing muted viewer to its audio clock. Audio-only members leave the viewer unchanged; Hide video and Close suppress automatic reopening until Show video is selected.
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
# state_file=config/state.json
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
| `YTDLP_POT_PROVIDER_URL` | Internal bgutil POT provider URL (default `http://192.168.0.10:4416`) |
| `YTDLP_COOKIES_FILE` | Optional cookies file used for one retry after an anonymous yt-dlp failure; in Docker, bind the client-local file read-only (the example path is `/run/secrets/yt-dlp-cookies.txt`) |

### Shared YouTube provider maintenance

The container pairs `bgutil-ytdlp-pot-provider==2.0.2` with the shared HTTP
provider `2.0.2`, and builds with stable yt-dlp `2026.10.21` and Node `24.22.1`.
Keep `youtube:player_client=mweb` and
`youtubepot-bgutilhttp:base_url=http://192.168.0.10:4416` unchanged.
The existing uv-owned runtime yt-dlp update path remains in place.

Coordinate the provider and every client plugin before deployment through the
canonical provider-coupled `homelab-infra` playbook. Check plugin discovery,
then exercise SoundBot's actual downloader arguments with a small public
simulation/download in isolated temporary storage, without starting Discord or
writing sound/state data. Provider `/ping` alone is not a download proof.
Do not provision or inspect cookies for this check, and do not automatically
roll back to the provider's vulnerable `1.3.2` release.

The development lock uses certifi `2026.10.19` for the
[emSign CA incident](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).
Docker's existing uv pip installation does not consume that lock, so this is
not proof of the runtime CA selection. Check the candidate's native Python
default and yt-dlp-selected trust stores for absence of `emSign ECC Root CA - G3`,
without adding an SSL override or changing the global trust configuration.

The targeted frontend lock update does not resolve all Gulp 4/CLI 2 build-chain
advisories. This npm dependency tree runs in the build stage; the runtime image
copies generated assets, not `node_modules`. The lock update alone does not
establish that the application or its build chain is fully patched.

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
├── config/                 # Runtime data (sounds, state)
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

> **Note:** A file lock prevents multiple instances from running simultaneously. If using Docker, stop it first with `docker compose stop`.

### Media timing

Video cuts decode the original at the saved start/end timestamps before
encoding the intermediate MKV at the existing browser width limit (1280px),
with even dimensions for H.264. This avoids a needless full-resolution
intermediate encode for 4K sources. Accurate cuts use two decoder and encoder
threads to bound retained frame memory, including tall portrait sources,
without changing the established width/aspect contract.
Do not use stream-copy seeking for cuts:
it retains preceding-keyframe frames and shifts that preroll into the clip.
Browser MP4s consume the accurately cut MKV (or apply the same cut directly to
the original when no intermediate exists). The muted web viewer follows the
selected sound's actual audio-playback clock, not the button-click time.

For an existing affected library, repair only demonstrated bad derivatives
from retained originals and saved timestamps. Preserve exact MKV/MP4 preimages
for operator-assisted rollback, generate and inspect candidates before atomic
replacement, and do not rewrite sound metadata or normalized OGGs just to fix
video. Deployments on the Apps fleet use the canonical `homelab-infra`
SoundBot digest pin and provider-coupled playbook, not this checkout's local
Compose example.

Run the isolated backend suite with `uv run pytest`. Its fixtures redirect
state and sound paths before imports; real FFmpeg timeline regressions require
`ffmpeg` and `ffprobe` on `PATH`.

### CLI tools

The native CLI uses the same sound services as Discord and the web UI, under
the existing exclusive state lock. It is an **offline administrative tool**:
stop the bot before running commands against its state, including `info` and
`list`. It uses the trusted local/container account and existing configuration,
not a Discord OAuth cookie. Never bypass the state lock or run a second state
owner against the live library. `--help` does not load settings or take the lock.

From a configured development checkout:

```bash
uv run soundbot-cli --help
# Equivalent module entry point:
uv run python -m soundbot.cli --help
```

For production, use the target's canonical operator procedure and accepted
image, existing environment, user, binds and network. The container interpreter
is `/app/.venv/bin/python`; a stopped container cannot accept `docker exec`.
Run only one offline command at a time in the coordinated bot-only window,
and restart the bot only after that process exits and releases the lock.
Do not start Discord or a second web server just to run the CLI.

Management commands print JSON and exit nonzero on failure. Names and aliases
resolve exactly; partial matches never choose a target. `add` and `import-file`
add **full-length** sounds without overwriting existing entries:

```bash
soundbot-cli add friday20221216 'https://www.youtube.com/watch?v=VIDEO_ID'
# Or prepare/download once elsewhere, then COPY that full source into retained
# SoundBot storage. The input remains untouched and provenance is preserved.
soundbot-cli import-file friday20221216 /input/report.mp4 \
  --source-url 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --source-title 'Weather Report 12/16/22'

# Inspect the saved full-length sound before cutting its retained original.
# Trim does not download again. Timestamps accept HH:MM:SS, MM:SS or seconds.
soundbot-cli info friday20221216
soundbot-cli trim friday20221216 8.9 17.7
soundbot-cli list

soundbot-cli group create lynchfridays
soundbot-cli group add lynchfridays friday20221216
soundbot-cli group list lynchfridays
soundbot-cli group list
soundbot-cli group remove lynchfridays friday20221216
soundbot-cli group delete lynchfridays

# Deletion permanently removes the retained original and derivatives.
# Remove memberships first, retain recovery copies, and name only owned entries.
soundbot-cli delete friday20221216 --yes

# Existing maintenance tools:
soundbot-cli clip VIDEO NAME START END [--volume N] [--overwrite]
soundbot-cli regenerate-audio [--sound NAME] [--dry-run]
soundbot-cli check-sounds [--remove]
soundbot-cli backfill-durations [--state-file PATH] [--sounds-folder PATH] [--write]
```

Unlike `import-file`, the legacy `clip` command does **not** copy its source:
it retains the absolute external path. Do not use it for full-length-first
staging, and do not remove its external source while the sound still uses it.
Inspect `list`/`info` and group membership before resuming a partial import;
a failed duplicate add is not permission to overwrite or download again.
Successful processing alone is not a playback check: verify actual served
audio/video, clip boundaries and group membership after restarting the bot.

`clip` requires the source to be reachable from wherever the bot runs. For
the Docker container, that means bind-mounting media shares (e.g.
`/mnt/tv:/mnt/tv:ro`) into the service.

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

### Slash Commands (Sound Management)

| Command | Description |
|---------|-------------|
| `/add <name> <url>` | Add a new sound from URL (YouTube, etc.) with optional start/end times |
| `/delete <name>` | Delete a sound |
| `/rename <old> <new>` | Rename a sound |
| `/trim <name>` | Set new start/end timestamps |
| `/adjust <name>` | Adjust timestamps relatively (add/remove seconds) |
| `/volume <name> <level>` | Set volume (0.1-5.0, 1.0 = normal) |
| `/info <name>` | Get sound details |
| `/list [search]` | List all sounds or search |

New and renamed sound names may contain up to **500 Unicode code points**. Existing persisted names remain loadable, and the on-disk storage slug is a separate short identifier.

### Text Commands (Playback)

| Command | Description |
|---------|-------------|
| `!soundname` | Play a sound (supports partial matching) |
| `!stop` | Stop current playback |
| `!leave` | Leave voice channel |
| `!sounds [search]` | Quick list of sounds |

The bot automatically joins the best voice channel:
1. The channel you're currently in
2. A channel with users who recently used the soundbot
3. The most populated channel

## License

MIT
