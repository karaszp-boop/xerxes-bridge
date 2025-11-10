#!/usr/bin/env bash
set -euo pipefail
UUID="${1:-229252442470304}"
NOW=$(date +%s000)
curl -s -o - -w '\nHTTP=%{http_code}\n' \
  -H "API-Key: Silne+1" -H "Content-Type: application/json" -H "X-Bridge-Origin: manual" \
  -d "{\"uuid\":\"$UUID\",\"ts\":$NOW,\
       \"meta\":{\"version\":\"probe\",\"modem\":{\"signalQuality\":21}},\
       \"values\":{\"temp\":23.7,\"rh\":51.0,\"voc\":42}}" \
  https://bridge.meta-mod.com/bridge/ingest
