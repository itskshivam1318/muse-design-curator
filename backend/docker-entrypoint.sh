#!/bin/sh
# Container start: fill an empty DATA_DIR from the snapshot baked into the image, then serve.
set -eu
BAKED=/home/user/app/data-baked
if [ ! -f "$DATA_DIR/dle.sqlite" ] && [ -d "$BAKED" ]; then
  mkdir -p "$DATA_DIR"
  cp -a "$BAKED/." "$DATA_DIR/"
  echo "data: copied the baked snapshot into $DATA_DIR"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
  --proxy-headers --forwarded-allow-ips='*'
