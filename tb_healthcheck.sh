#!/usr/bin/env bash
set -euo pipefail

cd /opt/xerxes-bridge

export MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"
export MONGO_DB="xerxes"
export MONGO_COLL="measurements"

set -a
source /opt/xerxes-bridge/tb_jwt.env
set +a

export AUDIT_LOOKBACK_DAYS=7

OUT=$(/opt/xerxes-bridge/tb_telemetry_audit.py 2>&1)

echo "$(date -Is) TB_HEALTHCHECK"
echo "$OUT"

# jednoduchý parse Status counts
NO_MONGO=$(echo "$OUT" | grep 'NO_MONGO:' | awk '{print $2}' || echo 0)
TB_NO_DATA=$(echo "$OUT" | grep 'TB_NO_DATA:' | awk '{print $2}' || echo 0)
TB_DELAY=$(echo "$OUT" | grep 'TB_DELAY:' | awk '{print $2}' || echo 0)

# prahové hodnoty – nastav podľa seba
THRESH_NO_MONGO=10
THRESH_TB_DELAY=3

if [ "${NO_MONGO:-0}" -gt "$THRESH_NO_MONGO" ] || [ "${TB_DELAY:-0}" -gt "$THRESH_TB_DELAY" ]; then
  MSG="TB healthcheck ALERT: NO_MONGO=$NO_MONGO TB_DELAY=$TB_DELAY TB_NO_DATA=$TB_NO_DATA"

  # TODO: doplň si vlastný webhook (Telegram / email)
  # curl -sS -X POST "https://api.telegram.org/bot<token>/sendMessage" \
  #   -d "chat_id=<chat_id>" -d "text=$MSG" >/dev/null

  echo "$MSG" >> /opt/xerxes-bridge/tb_healthcheck_alerts.log
fi
