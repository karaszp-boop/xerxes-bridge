#!/usr/bin/env bash
set -euo pipefail
cd /opt/xerxes-bridge

export TB_BASE="${TB_BASE:-https://eu.thingsboard.cloud}"
# TB_JWT nepotrebujeme – tokens.py volá TB cez token mapu

echo "------------------------------------------------------------------"
echo "TB TOKENS HEALTH (tokens.py validate)"
echo "------------------------------------------------------------------"

# validate vráti report – len ho zalogujeme a spočítame chyby
OUT=$(/opt/xerxes-bridge/tokens.py validate 2>&1 || true)
echo "$OUT"

BAD=$(echo "$OUT" | grep -i "INVALID" | wc -l || echo 0)

echo
echo "Invalid tokens: $BAD"
