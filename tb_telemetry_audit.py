#!/usr/bin/env python3
import os
import csv
import datetime as dt
from typing import Dict, Any, List, Tuple

from pymongo import MongoClient
from urllib import request, error
import json

# =========================
#  CONFIG
# =========================

TB_BASE = os.getenv("TB_BASE", "https://eu.thingsboard.cloud")
TB_JWT = os.getenv("TB_JWT")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/?authSource=admin")
DB_NAME = os.getenv("MONGO_DB", "xerxes")
COLL_MEAS = os.getenv("MONGO_COLL", "measurements")

# ako veľké okno chceme auditovať (dni)
LOOKBACK_DAYS = int(os.getenv("AUDIT_LOOKBACK_DAYS", "7"))
OUT_CSV = os.getenv("AUDIT_OUT_CSV", "/opt/xerxes-bridge/tb_telemetry_audit.csv")

TB_KEYS = ["temp", "rh", "pm10", "pm1_0", "pm2_5", "pm4_0", "voc", "nox", "light"]


# =========================
#  HTTP helper (TB API)
# =========================

def http_json(url: str, method="GET", data=None,
              headers=None, timeout=25) -> Tuple[int, Any]:
    req = request.Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        if isinstance(data, (dict, list)):
            data = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, data=data, timeout=timeout) as resp:
            body = resp.read()
            if not body:
                return resp.status, None
            try:
                return resp.status, json.loads(body.decode("utf-8"))
            except Exception:
                return resp.status, body.decode("utf-8", "ignore")
    except error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return -1, str(e)


# =========================
#  MONGO: last REAL per UUID
# =========================

def load_mongo_last_real() -> Dict[str, Dict[str, Any]]:
    client = MongoClient(MONGO_URI)
    coll = client.get_database(DB_NAME).get_collection(COLL_MEAS)

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)

    pipeline = [
        {
            "$match": {
                "ts": {"$gte": since},
                "meta.ingest.origin": "device",
                "$or": [
                    {"is_synth": {"$exists": False}},
                    {"is_synth": False},
                ],
            }
        },
        {
            "$group": {
                "_id": "$uuid",
                "last_ts": {"$max": "$ts"},
                "cnt": {"$sum": 1},
            }
        },
    ]

    out: Dict[str, Dict[str, Any]] = {}
    for d in coll.aggregate(pipeline):
        uuid = str(d["_id"])
        out[uuid] = {
            "last_mongo_ts": d["last_ts"],
            "cnt_lookback": d["cnt"],
        }
    return out


# =========================
#  TB: devices typu "sensor"
# =========================

def load_tb_devices() -> Dict[str, Dict[str, Any]]:
    if not TB_JWT:
        raise SystemError("TB_JWT missing. Run: source /opt/xerxes-bridge/tb_jwt.env")

    devices: Dict[str, Dict[str, Any]] = {}
    page = 0
    page_size = 100

    while True:
        url = (
            f"{TB_BASE}/api/tenant/devices?"
            f"pageSize={page_size}&page={page}"
            f"&sortProperty=createdTime&sortOrder=ASC"
        )
        code, body = http_json(url, headers={"X-Authorization": f"Bearer {TB_JWT}"})
        if code != 200 or not isinstance(body, dict):
            print(f"[audit] TB devices fetch failed page={page}: {code} {body}")
            break

        for dev in body.get("data", []):
            if dev.get("type") != "sensor":
                continue
            name = dev.get("name")
            dev_id = dev.get("id", {}).get("id")
            if not name or not dev_id:
                continue
            devices[name] = {
                "device_id": dev_id,
                "createdTime": dev.get("createdTime"),
            }

        if body.get("hasNext"):
            page += 1
        else:
            break

    print(f"[audit] TB sensors: {len(devices)}")
    return devices


# =========================
#  TB: last TS z telemetry
# =========================

def load_tb_last_ts(device_id: str) -> dt.datetime | None:
    keys_str = ",".join(TB_KEYS)
    url = (
        f"{TB_BASE}/api/plugins/telemetry/DEVICE/"
        f"{device_id}/values/timeseries?keys={keys_str}&limit=1"
    )
    code, body = http_json(url, headers={"X-Authorization": f"Bearer {TB_JWT}"})
    if code != 200 or not isinstance(body, dict):
        return None

    max_ts = None
    for arr in body.values():
        if not arr:
            continue
        ts_ms = arr[0].get("ts")
        if ts_ms is None:
            continue
        ts = dt.datetime.fromtimestamp(ts_ms / 1000.0)
        if max_ts is None or ts > max_ts:
            max_ts = ts
    return max_ts


# =========================
#  MAIN AUDIT
# =========================

def main():
    print(f"[audit] LOOKBACK_DAYS={LOOKBACK_DAYS}")
    print("[audit] Loading Mongo last REAL per uuid...")
    mongo_map = load_mongo_last_real()
    print(f"[audit] Mongo uuids: {len(mongo_map)}")

    print("[audit] Loading TB devices...")
    tb_devs = load_tb_devices()

    # všetky uuid z Mongo + TB (mená devices v TB sú uuid)
    all_ids = set(mongo_map.keys()) | set(tb_devs.keys())

    rows: List[Dict[str, Any]] = []

    for uuid in sorted(all_ids, key=str):
        tb_info = tb_devs.get(uuid)
        mongo_info = mongo_map.get(uuid)

        # ak je to backup-* device v TB, označíme BACKUP
        if uuid.startswith("backup-"):
            status = "BACKUP"
            last_tb_ts = None
            last_mongo_ts = None
            cnt_lookback = 0
            device_id = tb_info["device_id"] if tb_info else ""
            delta_min = None
        else:
            device_id = tb_info["device_id"] if tb_info else ""
            last_mongo_ts = mongo_info["last_mongo_ts"] if mongo_info else None
            cnt_lookback = mongo_info["cnt_lookback"] if mongo_info else 0
            last_tb_ts = load_tb_last_ts(device_id) if device_id else None

            # delta v minútach
            delta_min = None
            if last_mongo_ts and last_tb_ts:
                delta = (last_tb_ts - last_mongo_ts).total_seconds() / 60.0
                delta_min = round(delta, 2)

            # status
            if not mongo_info:
                status = "NO_MONGO"
            elif not last_tb_ts:
                status = "TB_NO_DATA"
            else:
                # obidve TS existujú
                if abs(delta_min) <= 15:
                    status = "OK"
                elif delta_min < -120:
                    status = "TB_DELAY"
                else:
                    status = "MINOR_OFFSET"

        rows.append({
            "uuid": uuid,
            "device_id": device_id,
            "last_mongo_ts": last_mongo_ts.isoformat() if last_mongo_ts else "",
            "cnt_lookback": cnt_lookback,
            "last_tb_ts": last_tb_ts.isoformat() if last_tb_ts else "",
            "delta_min": delta_min if delta_min is not None else "",
            "status": status,
        })

    # zapíš CSV
    fieldnames = [
        "uuid",
        "device_id",
        "last_mongo_ts",
        "cnt_lookback",
        "last_tb_ts",
        "delta_min",
        "status",
    ]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"[audit] Written CSV: {OUT_CSV}")
    from collections import Counter
    c = Counter(r["status"] for r in rows)
    print("[audit] Status counts:")
    for k, v in c.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
