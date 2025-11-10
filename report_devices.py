#!/usr/bin/env python3
import os, csv
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin")
DB = "xerxes"
COL_DEV = "devices"
COL_MEAS = "measurements"
OUT_CSV = "/opt/xerxes-bridge/devices_report.csv"

def iso(x):
    return x.astimezone(timezone.utc).isoformat() if isinstance(x, datetime) else (x or "")

def main():
    client = MongoClient(MONGO_URI)
    db = client[DB]
    devs = list(db[COL_DEV].find({}))
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    rows = []
    for d in devs:
        uuid = str(d.get("uuid",""))
        tb = d.get("tb") or {}
        meta = d.get("meta") or {}
        ingest = (meta.get("ingest") or {})
        last_real_ts = d.get("last_real_ts")
        last_seen_ts = d.get("last_seen_ts")
        last_seen_ip = d.get("last_seen_ip")

        # total counts per uuid
        total_real = db[COL_MEAS].count_documents({"uuid":uuid, "meta.ingest.synthetic": False})
        total_syn  = db[COL_MEAS].count_documents({"uuid":uuid, "meta.ingest.synthetic": True})

        # last 24h counts
        q_24h = {"uuid":uuid, "ts": {"$gte": since_24h}}
        real_24h = db[COL_MEAS].count_documents({**q_24h, "meta.ingest.synthetic": False})
        syn_24h  = db[COL_MEAS].count_documents({**q_24h, "meta.ingest.synthetic": True})

        rows.append({
            "uuid": uuid,
            "tb_id": tb.get("id",""),
            "tb_name": tb.get("name",""),
            "tb_label": tb.get("label",""),
            "token": tb.get("access_token",""),
            "has_token": "yes" if tb.get("access_token") else "no",
            "last_real_ts": iso(last_real_ts),
            "last_seen_ts": iso(last_seen_ts or ingest.get("received_at")),
            "last_seen_ip": last_seen_ip or ingest.get("source_ip",""),
            "total_real": total_real,
            "total_synthetic": total_syn,
            "real_24h": real_24h,
            "synthetic_24h": syn_24h,
        })

    # sort: najprv bez real za 24h, potom podľa last_real_ts desc
    rows.sort(key=lambda r: (-(r["real_24h"]==0), r["last_real_ts"]), reverse=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [
            "uuid","tb_id","tb_name","tb_label","token","has_token",
            "last_real_ts","last_seen_ts","last_seen_ip",
            "total_real","total_synthetic","real_24h","synthetic_24h"
        ])
        w.writeheader()
        for r in rows: w.writerow(r)

    print(f"[OK] Report written: {OUT_CSV}  (rows={len(rows)})")
    # zhrnutie
    no_token = sum(1 for r in rows if r["has_token"]=="no")
    no_real24 = sum(1 for r in rows if r["real_24h"]==0)
    print(f"[SUMMARY] devices with NO token: {no_token}, devices with NO real in 24h: {no_real24}")

if __name__ == "__main__":
    main()
