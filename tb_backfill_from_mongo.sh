#!/usr/bin/env bash
set -euo pipefail

cd /opt/xerxes-bridge

export MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"
export MONGO_DB="xerxes"
export MONGO_COLL="measurements"

set -a
source /opt/xerxes-bridge/tb_jwt.env
set +a

# napr. posledných 7 dní
LOOKBACK_MIN=$((7*24*60))
export LOOKBACK_MIN

echo "$(date -Is) TB_BACKFILL start (LOOKBACK_MIN=$LOOKBACK_MIN)"
python3 /opt/xerxes-bridge/tb_sync_from_mongo.py
echo "$(date -Is) TB_BACKFILL done"
