#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

mkdir -p data uploads playlists logs
exec python3 app.py
