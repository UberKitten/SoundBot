# Build static assets for UI
FROM node:24 as node-builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY ./web ./web
# Outputs files in web/dist/
RUN npm run build

# Used by both builder and soundbot
FROM python:3.14 as python-base
WORKDIR /app

# https://docs.python.org/3/using/cmdline.html
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1

# Dependencies needed by discord.py for voice and python-ffmpeg
RUN apt-get update && apt-get install -y libffi-dev libnacl-dev ffmpeg

# Creates the virtual environment and wheel for soundbot
FROM python-base as python-builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml ./
COPY ./src ./src

# Build Python wheel in /app/dist/ and virtual environment in /app/.venv/
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python -e ".[unix]" && \
    uv build

# Final image
FROM python-base as soundbot

COPY --from=node-builder /app/web/dist ./web/dist

# Templates are used at runtime by web server
COPY --from=node-builder /app/web/template ./web/template

COPY --from=python-builder /app/.venv ./.venv
COPY --from=python-builder /app/dist ./dist

# Install uv and the wheel built previously
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN uv pip install --python .venv/bin/python ./dist/*.whl

# Update yt-dlp to latest version at build time
RUN ./.venv/bin/yt-dlp --update || true

CMD ./.venv/bin/python -m soundbot
