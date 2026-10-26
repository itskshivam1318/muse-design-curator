#!/bin/sh
# Container start: if DATA_DIR is not the baked data/ and has no database yet (e.g. a freshly
# mounted volume), copy the baked snapshot into it; then serve API + app on $PORT.
set -eu
BAKED=/home/user/app/data
if [ "$DATA_DIR" != "$BAKED" ] && [ ! -f "$DATA_DIR/dle.sqlite" ] && [ -f "$BAKED/dle.sqlite" ]; then
  mkdir -p "$DATA_DIR"
  cp -a "$BAKED/." "$DATA_DIR/"
  echo "data: copied the baked snapshot into $DATA_DIR"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
  --proxy-headers --forwarded-allow-ips='*'
