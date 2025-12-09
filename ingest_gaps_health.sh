#!/usr/bin/env bash
set -euo pipefail
cd /opt/xerxes-bridge

# lookback v minútach (3 hodiny default)
MON_LOOKBACK_MIN="${MON_LOOKBACK_MIN:-180}"

export MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"
export MONGO_DB="xerxes"
export MONGO_COLL="measurements"

echo "=== INGEST GAPS (last ${MON_LOOKBACK_MIN} min) ==="

# použijeme existujúci monitor_telemetry.py, ale budeme čítať len RAW a MEAS
/opt/xerxes-bridge/monitor_telemetry.py 2>/dev/null | \
  awk '
    /^UUID/ { hdr=1; next }
    hdr && NF>0 {
      uuid=$1; raw=$2; meas=$3; tb=$4; status=$5;
      # derivácia statusu pre ingest:
      # ak raw je "-" alebo prázdne -> ingest gap
      if (raw=="-" || raw=="") {
        print uuid, raw, meas, tb, "INGEST_GAP";
      }
    }
  '
