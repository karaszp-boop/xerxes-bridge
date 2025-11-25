#!/usr/bin/env python3
import os
import sys
import time
import datetime as dt
from typing import Dict, Any, List, Tuple

from pymongo import MongoClient
from urllib import request, error
import json

# ========= CONFIG =========

TB_BASE = os.getenv("TB_BASE", "https://eu.thingsboard.cloud")
TB_JWT = os.getenv("TB_JWT")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/?authSource=admin")
MONGO_DB = os.getenv("MONGO_DB", "xerxes")
COLL_MEAS = os.getenv("MONGO_COLL", "measurements")
COLL_RAW = "ingest_raw"

LOOKBACK_MIN = int(os.getenv("MON_LOOKBACK_MIN", "180"))  # 3 hodiny
TB_KEYS = ["temp", "rh", "pm10", "pm1_0", "pm2_5", "pm4_0", "voc", "nox", "light"]

# ANSI farby
C_RESET = "\033[0m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_CYAN = "\033[36m"
C_GRAY = "\033[90m"


def http_json(url: str, method="GET", data=None, headers=None, timeout=10) -> Tuple[int, Any]:
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


def load_mongo_maps(lookback_min: int):
    client = MongoClient(MONGO_URI)
    dbx = client[MONGO_DB]

    since = dt.datetime.utcnow() - dt.timedelta(minutes=lookback_min)

    # last ingest_raw per uuid
    raw_map: Dict[str, dt.datetime] = {}
    for d in dbx[COLL_RAW].aggregate([
        {"$match": {"ts": {"$gte": since}}},
        {"$group": {"_id": "$uuid", "last_ts": {"$max": "$ts"}}}
    ]):
        raw_map[str(d["_id"])] = d["last_ts"]

    # last measurements per uuid
    meas_map: Dict[str, dt.datetime] = {}
    for d in dbx[COLL_MEAS].aggregate([
        {"$match": {"ts": {"$gte": since}}},
        {"$group": {"_id": "$uuid", "last_ts": {"$max": "$ts"}}}
    ]):
        meas_map[str(d["_id"])] = d["last_ts"]

    return raw_map, meas_map


def load_tb_last_ts_for_uuids(uuids: List[str]) -> Dict[str, dt.datetime]:
    if not TB_JWT:
        return {}

    out: Dict[str, dt.datetime] = {}
    for u in uuids:
        url = (
            f"{TB_BASE}/api/plugins/telemetry/DEVICE/"
            f"{lookup_device_id(u)}/values/timeseries?keys={','.join(TB_KEYS)}&limit=1"
        )
        code, body = http_json(url, headers={"X-Authorization": f"Bearer {TB_JWT}"})
        if code != 200 or not isinstance(body, dict):
            continue
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
        if max_ts:
            out[u] = max_ts
    return out


_device_id_cache: Dict[str, str] = {}


def lookup_device_id(uuid: str) -> str:
    # cache hit
    if uuid in _device_id_cache:
        return _device_id_cache[uuid]

    if not TB_JWT:
        return ""

    # lookup by name
    url = f"{TB_BASE}/api/tenant/devices?deviceName={uuid}"
    code, body = http_json(url, headers={"X-Authorization": f"Bearer {TB_JWT}"})
    dev_id = ""
    if code == 200 and isinstance(body, dict):
        dev_id = (body.get("id") or {}).get("id") or ""

    _device_id_cache[uuid] = dev_id
    return dev_id


def classify(uuid: str,
             last_raw: dt.datetime | None,
             last_meas: dt.datetime | None,
             last_tb: dt.datetime | None) -> Tuple[str, str]:
    """
    Vráti (status, farba)
    """
    now = dt.datetime.utcnow()

    def age_minutes(ts: dt.datetime | None) -> float | None:
        if not ts:
            return None
        return (now - ts).total_seconds() / 60.0

    ar = age_minutes(last_raw)
    am = age_minutes(last_meas)
    atb = age_minutes(last_tb)

    # LOGIKA:
    # - OFFLINE: nič v raw ani measurements
    if last_raw is None and last_meas is None:
        return "OFFLINE", C_GRAY

    # - BRIDGE_ONLY: raw existuje, meas nie
    if last_raw is not None and last_meas is None:
        return "BRIDGE_DROP", C_RED

    # - MONGO_ONLY: meas existuje, TB nie
    if last_meas is not None and last_tb is None:
        return "TB_NO_DATA", C_YELLOW

    # - všetko existuje -> skús delta
    delta = None
    if last_meas and last_tb:
        delta = (last_tb - last_meas).total_seconds() / 60.0

    if delta is not None:
        if abs(delta) <= 15:
            return "OK", C_GREEN
        elif delta < -60:
            return "TB_DELAY", C_YELLOW
        else:
            return "MINOR_OFFSET", C_CYAN

    return "UNKNOWN", C_GRAY


def main():
    lookback = LOOKBACK_MIN
    if len(sys.argv) > 1:
        try:
            lookback = int(sys.argv[1])
        except Exception:
            pass

    print(f"{C_CYAN}=== TELEMETRY MONITOR (last {lookback} min) ==={C_RESET}")

    raw_map, meas_map = load_mongo_maps(lookback)

    # zoznam všetkých uuid, ktoré sa aspoň niekde objavili
    all_uuids = sorted(set(raw_map.keys()) | set(meas_map.keys()), key=str)

    # TB last_ts pre všetky uuid (ak TB_JWT je nastavený)
    tb_map: Dict[str, dt.datetime] = {}
    if TB_JWT:
        print("[monitor] Fetching TB telemetry timestamps (may take a while)...")
        tb_map = {}
        for u in all_uuids:
            dev_id = lookup_device_id(u)
            if not dev_id:
                continue
            url = (
                f"{TB_BASE}/api/plugins/telemetry/DEVICE/"
                f"{dev_id}/values/timeseries?keys={','.join(TB_KEYS)}&limit=1"
            )
            code, body = http_json(url, headers={"X-Authorization": f"Bearer {TB_JWT}"})
            if code != 200 or not isinstance(body, dict):
                continue
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
            if max_ts:
                tb_map[u] = max_ts

    rows = []
    now = dt.datetime.utcnow()

    for u in all_uuids:
        last_raw = raw_map.get(u)
        last_meas = meas_map.get(u)
        last_tb = tb_map.get(u)
        status, color = classify(u, last_raw, last_meas, last_tb)

        def age(ts):
            if not ts:
                return ""
            return f"{int((now - ts).total_seconds()/60)}m"

        rows.append({
            "uuid": u,
            "last_raw": last_raw,
            "last_meas": last_meas,
            "last_tb": last_tb,
            "age_raw": age(last_raw),
            "age_meas": age(last_meas),
            "age_tb": age(last_tb),
            "status": status,
            "color": color,
        })

    # zoradené podľa kritičnosti
    order = {"OFFLINE": 3, "BRIDGE_DROP": 3, "TB_NO_DATA": 2, "TB_DELAY": 2,
             "MINOR_OFFSET": 1, "OK": 0, "UNKNOWN": 4}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["uuid"]))

    print(f"{'UUID':<15} {'raw':<7} {'meas':<7} {'TB':<7}  STATUS")
    print("-" * 60)
    for r in rows:
        c = r["color"]
        print(
            f"{c}{r['uuid']:<15} "
            f"{r['age_raw']:<7} {r['age_meas']:<7} {r['age_tb']:<7}  "
            f"{r['status']}{C_RESET}"
        )


if __name__ == "__main__":
    main()
