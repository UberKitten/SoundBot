FROM node:21 as node-builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY ./web ./
RUN npm run build
# Outputs files in web/dist/

FROM python:3.12 as python-base

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y libffi-dev libnacl-dev python3-dev ffmpeg

WORKDIR /app

FROM python-base as python-builder

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.7.1

RUN pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && \
    poetry install --only=main --no-root

FROM python-base as final

COPY --from=python-builder /app/.venv ./.venv
COPY --from=python-builder /app/dist .

RUN ./.venv/bin/pip install *.whl

CMD ./.venv/bin/python -m app
