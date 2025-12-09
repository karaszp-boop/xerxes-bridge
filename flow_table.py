#!/usr/bin/env python3
import os
import sys
import json
import requests
from pymongo import MongoClient
from datetime import datetime, timedelta

TB_BASE = os.getenv("TB_BASE", "https://eu.thingsboard.cloud")
TB_JWT  = os.getenv("TB_JWT")

MONGO_URI  = os.getenv("MONGO_URI")
MONGO_DB   = os.getenv("MONGO_DB", "xerxes")
MONGO_COLL = os.getenv("MONGO_COLL", "measurements")

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "24"))
since_dt = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)

# ----------------------------------------------------------------------
# LOAD MONGO MAP
# ----------------------------------------------------------------------
def load_mongo():
    client = MongoClient(MONGO_URI)
    coll = client[MONGO_DB][MONGO_COLL]
    docs = coll.aggregate([
        {"$match": {"ts": {"$gte": since_dt}}},
        {"$group": {
            "_id": "$uuid",
            "count": {"$sum": 1},
            "last_ts": {"$max": "$ts"}
        }}
    ])
    out = {}
    for d in docs:
        out[str(d["_id"])] = {
            "count": d["count"],
            "last_ts": d["last_ts"].isoformat()
        }
    return out

# ----------------------------------------------------------------------
# LOAD TB MAP
# ----------------------------------------------------------------------
def load_tb():
    hdr = {"X-Authorization": f"Bearer {TB_JWT}"}
    devs = requests.get(f"{TB_BASE}/api/tenant/devices?pageSize=500&page=0", headers=hdr).json()
    out = {}
    for d in devs.get("data", []):
        uuid = d["name"] if d["name"].isdigit() else None
        if not uuid:
            continue
        did = d["id"]["id"]

        ts_api = f"{TB_BASE}/api/plugins/telemetry/DEVICE/{did}/values/timeseries?keys=temp"
        ts = requests.get(ts_api, headers=hdr).json()
        if "temp" in ts:
            last_ts = ts["temp"][0]["ts"]
            out[uuid] = {
                "device_id": did,
                "count": len(ts["temp"]),
                "last_ts": datetime.utcfromtimestamp(last_ts/1000).isoformat() + "Z"
            }
        else:
            out[uuid] = {
                "device_id": did,
                "count": 0,
                "last_ts": ""
            }
    return out

# ----------------------------------------------------------------------
# CLASSIFICATION
# ----------------------------------------------------------------------
def classify(mongo_map, tb_map):
    uuids = set(mongo_map.keys()) | set(tb_map.keys())
    rows = []

    for u in sorted(uuids):
        has_mongo = u in mongo_map
        has_tb    = u in tb_map

        if has_mongo and has_tb:
            path = "both"
        elif has_mongo:
            path = "new_only"
        elif has_tb:
            path = "old_only"
        else:
            path = "no_data"

        rows.append({
            "uuid": u,
            "device_id": tb_map[u]["device_id"] if u in tb_map else "",
            "path_class": path,
            "has_mongo": 1 if has_mongo else 0,
            "has_tb": 1 if has_tb else 0,
            "mongo_count": mongo_map[u]["count"] if has_mongo else 0,
            "tb_count": tb_map[u]["count"] if has_tb else 0,
            "last_mongo_ts": mongo_map[u]["last_ts"] if has_mongo else "",
            "last_tb_ts": tb_map[u]["last_ts"] if has_tb else "",
        })
    return rows

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    if not TB_JWT:
        print("ERROR: missing TB_JWT. Run: source tb_jwt.env", file=sys.stderr)
        sys.exit(1)

    if not MONGO_URI:
        print("ERROR: missing MONGO_URI", file=sys.stderr)
        sys.exit(1)

    mongo_map = load_mongo()
    tb_map = load_tb()
    rows = classify(mongo_map, tb_map)

    print("uuid,device_id,path_class,has_mongo,has_tb,mongo_count,tb_count,last_mongo_ts,last_tb_ts")
    for r in rows:
        print(",".join([
            r["uuid"],
            r["device_id"],
            r["path_class"],
            str(r["has_mongo"]),
            str(r["has_tb"]),
            str(r["mongo_count"]),
            str(r["tb_count"]),
            r["last_mongo_ts"],
            r["last_tb_ts"],
        ]))

if __name__ == "__main__":
    main()
