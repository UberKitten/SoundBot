#!/bin/sh
PORT="${1:-8080}"
hypercorn app.web.app:app --bind "[::]:$PORT" --reload
