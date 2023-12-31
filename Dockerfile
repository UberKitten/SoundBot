# Build static assets for UI
FROM node:21 as node-builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY ./web ./web
# Outputs files in web/dist/
RUN npm run build

# Used by both builder and soundbot
FROM python:3.12 as python-base
WORKDIR /app

# https://docs.python.org/3/using/cmdline.html
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1

# Dependencies needed by discord.py for voice and python-ffmpeg
RUN apt-get update && apt-get install -y libffi-dev libnacl-dev ffmpeg

# Creates the virtual environment and wheel for soundbot
FROM python-base as python-builder

# https://pip.pypa.io/en/stable/cli/pip/
ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.7.1

# Set up poetry pinned to a specific build to keep builds reproducible
RUN pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./
COPY ./src ./

# Build Python wheel in /app/dist/ and virtual environment in /app/.venv/
RUN poetry config virtualenvs.in-project true && \
    poetry install --only=main --no-root && \
    poetry build

# Final image
FROM python-base as soundbot

COPY --from=node-builder /app/web/dist ./web/dist

# Templates are used at runtime by web server
COPY --from=node-builder /app/web/template ./web/template

COPY --from=python-builder /app/.venv ./.venv
COPY --from=python-builder /app/dist .

# Installs the wheel built previously
RUN ./.venv/bin/pip install *.whl

CMD ./.venv/bin/python -m soundbot
