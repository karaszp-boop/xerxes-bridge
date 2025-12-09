#!/usr/bin/env bash
set -euo pipefail

cd /opt/xerxes-bridge

# ── Konfigurácia ───────────────────────────────────────────────
MON_LOOKBACK_MIN="${MON_LOOKBACK_MIN:-180}"   # minúty pre monitor_telemetry
TG_TOKEN="${TG_TOKEN:-}"                      # Telegram bot token
TG_CHAT_ID="${TG_CHAT_ID:-}"                  # chat_id s @xerxes_health_bot
IOT_HEALTH_ALERT_ONLY="${IOT_HEALTH_ALERT_ONLY:-0}"  # 0 = full, 1 = alert-only

if [[ -z "$TG_TOKEN" || -z "$TG_CHAT_ID" ]]; then
  echo "ERROR: TG_TOKEN alebo TG_CHAT_ID nie sú nastavené"
  exit 1
fi

# ── 1) Spusti full health a zachyť výstup ───────────────────────
OUT=$(
  MON_LOOKBACK_MIN="$MON_LOOKBACK_MIN" \
  PYTHONWARNINGS="ignore::DeprecationWarning" \
  NO_COLOR=1 \
  ./iot_health_full.sh
)

# ── 2) Ulož report do súboru v reports/ ─────────────────────────
mkdir -p /opt/xerxes-bridge/reports

TS_UTC=$(date -Is)                # napr. 2025-12-08T13:10:47+00:00
SAFE_TS=${TS_UTC//:/-}            # 2025-12-08T13-10-47+00-00
REPORT_FILE="/opt/xerxes-bridge/reports/iot_health_${SAFE_TS}.txt"

printf '%s\n' "$OUT" > "$REPORT_FILE"
ln -sf "$REPORT_FILE" /opt/xerxes-bridge/reports/iot_health_latest.txt

echo "DEBUG: report file = $REPORT_FILE"
ls -l "$REPORT_FILE"

HOSTNAME_SHORT=$(hostname)
CAPTION="✅ Xerxes IoT full health report
host: ${HOSTNAME_SHORT}
time: ${TS_UTC}
file: $(basename "$REPORT_FILE")"

# 3) ALERT ONLY mód – posielaj iba ak sú problémy
# ------------------------------------------------
if [[ "${IOT_HEALTH_ALERT_ONLY:-0}" = "1" ]]; then
  # --- sumarizácia z OUT /报告 ---
  # OUT už obsahuje text z iot_health_full.sh
  # sem vlož svoj existujúci kód, ktorý počíta:
  #   HOST_ALERT, BRIDGE_ALERT, TB_ALERT, STANO_ALERT,
  #   FLOW_ALERT, GAP_ALERT, TOKEN_ALERT, CF_ALERT
  # (ten už v skripte máš – NECHAJME HO TAK AK JE OK)

  ALERT_LINES=()
  [[ -n "${HOST_ALERT:-}"   ]] && ALERT_LINES+=("$HOST_ALERT")
  [[ -n "${BRIDGE_ALERT:-}" ]] && ALERT_LINES+=("$BRIDGE_ALERT")
  [[ -n "${TB_ALERT:-}"     ]] && ALERT_LINES+=("$TB_ALERT")
  [[ -n "${STANO_ALERT:-}"  ]] && ALERT_LINES+=("$STANO_ALERT")
  [[ -n "${FLOW_ALERT:-}"   ]] && ALERT_LINES+=("$FLOW_ALERT")
  [[ -n "${GAP_ALERT:-}"    ]] && ALERT_LINES+=("$GAP_ALERT")
  [[ -n "${TOKEN_ALERT:-}"  ]] && ALERT_LINES+=("$TOKEN_ALERT")
  [[ -n "${CF_ALERT:-}"     ]] && ALERT_LINES+=("$CF_ALERT")

  if (( ${#ALERT_LINES[@]} == 0 )); then
    echo "ALERT_ONLY: nič kritické – žiadna správa do Telegramu."
    exit 0
  fi

  ALERT_MSG=$'⚠️ Xerxes IoT ALERT '"(${TS_UTC})"$'\n'"host: ${HOSTNAME_SHORT}\n"
  for line in "${ALERT_LINES[@]}"; do
    ALERT_MSG+="$line"$'\n'
  done

  echo "DEBUG: sending ALERT_ONLY Telegram message"
  curl -sS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT_ID}" \
    --data-urlencode "text=${ALERT_MSG}" \
    --data-urlencode "disable_web_page_preview=true" >/dev/null || true

  exit 0
fi

# 4) FULL MOD – ráno/večer: krátky header + celý report v častiach
# ----------------------------------------------------------------
CAPTION="✅ Xerxes IoT full health report
host: ${HOSTNAME_SHORT}
time: ${TS_UTC}
file: $(basename "$REPORT_FILE")"

# najprv krátky header (bez celého textu)
curl -sS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT_ID}" \
  --data-urlencode "text=${CAPTION}" \
  --data-urlencode "disable_web_page_preview=true" >/dev/null || true

# potom pošli celý text reportu po častiach (limit ~3500 znakov)
MAX=3500
TEXT="$OUT"
LEN=${#TEXT}
PART=1
TOTAL=$(( (LEN + MAX - 1) / MAX ))

echo "DEBUG: sending full report in ${TOTAL} part(s)"

while [[ -n "$TEXT" ]]; do
  CHUNK=${TEXT:0:MAX}
  TEXT=${TEXT:MAX}
  MSG="(part ${PART}/${TOTAL})
${CHUNK}"

  curl -sS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT_ID}" \
    --data-urlencode "text=${MSG}" \
    --data-urlencode "disable_web_page_preview=true" >/dev/null || true

  PART=$((PART+1))
done

echo "Sent Telegram text report in $((PART-1)) part(s)."
exit 0
