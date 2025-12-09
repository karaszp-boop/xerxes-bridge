#!/usr/bin/env bash
set -euo pipefail

cd /opt/xerxes-bridge

# ──────────────────────────────────────────────────────────────────────
# 0) ENV
# ──────────────────────────────────────────────────────────────────────
set -a
source /opt/xerxes-bridge/tb_jwt.env
set +a

export MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"
export MONGO_DB="xerxes"
export MONGO_COLL="measurements"

# LOOKBACK pre tokové analýzy (v hodinách)
export LOOKBACK_HOURS="${LOOKBACK_HOURS:-3}"
MON_LOOKBACK_MIN=$(( LOOKBACK_HOURS * 60 ))
export MON_LOOKBACK_MIN

TS_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
OUT_DIR="/opt/xerxes-bridge/reports"
mkdir -p "$OUT_DIR"

REPORT_TXT="$OUT_DIR/iot_health_${TS_UTC}.txt"
FLOW_CSV="$OUT_DIR/flow_table_${TS_UTC}.csv"
AUDIT_CSV="/opt/xerxes-bridge/tb_telemetry_audit.csv"

# ──────────────────────────────────────────────────────────────────────
# 1) HETZNER / HOST HEALTH
# ──────────────────────────────────────────────────────────────────────
HOST_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "1) HETZNER / HOST HEALTH (ubuntu-4gb-hel1-2)"
    echo "------------------------------------------------------------------"
    echo "TIME (UTC):  $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    echo

    echo "[uptime / load / users]"
    uptime
    echo

    echo "[disk usage /]"
    df -h / | sed '1,2p;3,$d'
    echo

    echo "[memory (MiB)]"
    free -m
    echo

    echo "[docker ps – kritické kontajnery]"
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    echo
  } 2>&1
)

# ──────────────────────────────────────────────────────────────────────
# 2) BRIDGE + MONGO HEALTH
# ──────────────────────────────────────────────────────────────────────
BRIDGE_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "2) BRIDGE / MONGO HEALTH"
    echo "------------------------------------------------------------------"
    ./bridge_health.sh
    echo
  } 2>&1
)

# ──────────────────────────────────────────────────────────────────────
# 3) THINGSBOARD HEALTH + AUDIT (tb_healthcheck.sh + tb_telemetry_audit.py)
# ──────────────────────────────────────────────────────────────────────
TB_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "3) THINGSBOARD HEALTH + AUDIT (tb_healthcheck.sh)"
    echo "------------------------------------------------------------------"
    ./tb_healthcheck.sh
    echo
  } 2>&1
)

# ──────────────────────────────────────────────────────────────────────
# 4) TELEMETRY MONITOR (Mongo vs TB – „lag“ v minútach)
# ──────────────────────────────────────────────────────────────────────
MON_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "4) TELEMETRY MONITOR (Mongo vs TB, posledných ${MON_LOOKBACK_MIN} min)"
    echo "------------------------------------------------------------------"
    ./monitor_telemetry.py || true
    echo
  } 2>&1
)

# ──────────────────────────────────────────────────────────────────────
# 5) TOKY SENZOROV (flow_table.py → old_only / both / new_only / no_data)
# ──────────────────────────────────────────────────────────────────────
./flow_table.py > "$FLOW_CSV"

OLD_ONLY_COUNT=$(awk -F, 'NR>1 && $3=="old_only"{c++} END{print c+0}' "$FLOW_CSV")
BOTH_COUNT=$(awk -F, 'NR>1 && $3=="both"{c++} END{print c+0}' "$FLOW_CSV")
NEW_ONLY_COUNT=$(awk -F, 'NR>1 && $3=="new_only"{c++} END{print c+0}' "$FLOW_CSV")
NO_DATA_COUNT=$(awk -F, 'NR>1 && $3=="no_data"{c++} END{print c+0}' "$FLOW_CSV")

FLOW_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "5) TOKY SENZOROV (flow_table.py, LOOKBACK_HOURS=${LOOKBACK_HOURS})"
    echo "    path_class:"
    echo "      old_only = C (Stano → TB direct, bez Bridge/Mongo v okne)"
    echo "      both     = B+C (Bridge + direct)"
    echo "      new_only = B (Bridge → Mongo → TB len cez sync)"
    echo "      no_data  = nič v okne (offline / dlhšie ticho)"
    echo "------------------------------------------------------------------"
    echo
    echo "Súhrn:"
    echo "  old_only (C – direct only) : ${OLD_ONLY_COUNT}"
    echo "  both     (B+C – mix)       : ${BOTH_COUNT}"
    echo "  new_only (B – čistý Bridge): ${NEW_ONLY_COUNT}"
    echo "  no_data  (offline)         : ${NO_DATA_COUNT}"
    echo

    echo "Top old_only (C – priame Stano→TB):"
    awk -F, 'NR==1 || $3=="old_only"' "$FLOW_CSV" | head -n 10
    echo

    echo "Top both (B+C – mix Bridge+direct):"
    awk -F, 'NR==1 || $3=="both"' "$FLOW_CSV" | head -n 10
    echo

    echo "Celá flow tabuľka je uložená v:"
    echo "  $FLOW_CSV"
    echo
  } 2>&1
)

# ──────────────────────────────────────────────────────────────────────
# 6) TB TELEMETRY AUDIT (tb_telemetry_audit.csv – posledných 7 dní)
# ──────────────────────────────────────────────────────────────────────
AUDIT_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "6) TB TELEMETRY AUDIT (tb_telemetry_audit.csv – posledných 7 dní)"
    echo "------------------------------------------------------------------"
    if [ -f "$AUDIT_CSV" ]; then
      TOTAL=$(awk -F, 'NR>1{c++} END{print c+0}' "$AUDIT_CSV")
      OK=$(awk -F, 'NR>1 && $7!="" && $8==0{c++} END{print c+0}' "$AUDIT_CSV")
      NO_MONGO=$(awk -F, 'NR>1 && $3=="NO_MONGO"{c++} END{print c+0}' "$AUDIT_CSV")
      TB_NO_DATA=$(awk -F, 'NR>1 && $3=="TB_NO_DATA"{c++} END{print c+0}' "$AUDIT_CSV")

      echo "Počet riadkov v audite: $TOTAL"
      echo "  OK        : $OK"
      echo "  NO_MONGO  : $NO_MONGO"
      echo "  TB_NO_DATA: $TB_NO_DATA"
      echo
      echo "Top problematické riadky (NO_MONGO alebo TB_NO_DATA):"
      awk -F, 'NR==1 || $3=="NO_MONGO" || $3=="TB_NO_DATA"' "$AUDIT_CSV" | head -n 15
      echo
    else
      echo "Audit CSV ($AUDIT_CSV) neexistuje – spusti ./tb_healthcheck.sh aspoň raz."
      echo
    fi
  } 2>&1
)

# ──────────────────────────────────────────────────────────────────────
# 7) CLOUDFLARE LAYER HEALTH (bridge.meta-mod.com cez CF)
# ──────────────────────────────────────────────────────────────────────
CF_SEC=$(
  {
    echo "------------------------------------------------------------------"
    echo "7) CLOUDFLARE / EDGE HEALTH (https://bridge.meta-mod.com/health)"
    echo "------------------------------------------------------------------"

    TMP=$(mktemp)

    # HEAD request – uloží headre do TMP
    curl -sS -D "$TMP" -o /dev/null --max-time 5 \
      "https://bridge.meta-mod.com/health" || echo "curl FAILED"

    # Status code
    CF_HTTP=$(awk 'toupper($1) ~ /^HTTP/ {print $2}' "$TMP")

    # CF-Ray header (ak chýba → prázdne)
    CF_RAY=$(awk 'tolower($1)=="cf-ray:" {print $2}' "$TMP")

    rm -f "$TMP"

    echo "HTTP=${CF_HTTP:-N/A}  CF-RAY=${CF_RAY:-none}"
    echo
  } 2>&1
)
# ──────────────────────────────────────────────────────────────────────
# 8) ZLOŽ REPORT DO TXT
# ──────────────────────────────────────────────────────────────────────
{
  echo "=================================================================="
  echo "  Xerxes IoT FULL Health Report"
  echo "  Generated: ${TS_UTC} (UTC)"
  echo "  LOOKBACK_HOURS=${LOOKBACK_HOURS}"
  echo "=================================================================="
  echo

  echo "$HOST_SEC"
  echo "$BRIDGE_SEC"
  echo "$TB_SEC"
  echo "$MON_SEC"
  echo "$FLOW_SEC"
  echo "$AUDIT_SEC"
  echo "$CF_SEC"

} > "$REPORT_TXT"

# Vypíš do konzoly pri manuálnom spustení
cat "$REPORT_TXT"
echo "------------------------------------------------------------------"
echo "8) STANO → BRIDGE INGEST GAPS (ingest_gaps_health.sh)"
echo "------------------------------------------------------------------"
/opt/xerxes-bridge/ingest_gaps_health.sh || echo "ingest_gaps_health FAILED"
echo

echo "------------------------------------------------------------------"
echo "9) THINGSBOARD TOKENS HEALTH (tb_tokens_health.sh)"
echo "------------------------------------------------------------------"
/opt/xerxes-bridge/tb_tokens_health.sh || echo "tb_tokens_health FAILED"
echo

echo "------------------------------------------------------------------"
echo "10) MONGO STORAGE HEALTH (mongo_storage_health.sh)"
echo "------------------------------------------------------------------"
/opt/xerxes-bridge/mongo_storage_health.sh || echo "mongo_storage_health FAILED"
echo
