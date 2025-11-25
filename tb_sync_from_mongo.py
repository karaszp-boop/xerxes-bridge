#!/usr/bin/env python3
import os
import json
import datetime as dt
from typing import Dict, Any, List, Tuple
from urllib import request, parse, error
from pymongo import MongoClient

TB_BASE = os.getenv("TB_BASE", "https://eu.thingsboard.cloud")
TB_JWT  = os.getenv("TB_JWT")
TB_REFRESH = os.getenv("TB_REFRESH")  # for refresh flow

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/?authSource=admin")
DB_NAME   = os.getenv("MONGO_DB", "xerxes")
COLL_MEAS = os.getenv("MONGO_COLL", "measurements")
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin",
)

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["xerxes"]
coll_meas = db["measurements"]

DEVICE_TYPE = os.getenv("TB_DEVICE_TYPE", "sensor")
DEVICE_PROFILE_NAME = os.getenv("TB_DEVICE_PROFILE", "Xerxes Bridge – Sensor")
LOOKBACK_MIN = int(os.getenv("LOOKBACK_MIN", "60"))

TOKEN_MAP_PATH = os.getenv("TOKEN_MAP_JSON", "/opt/xerxes-bridge/tokens.json")
TOKEN_MAP: Dict[str, str] = {}
if os.path.exists(TOKEN_MAP_PATH):
    try:
        with open(TOKEN_MAP_PATH, "r") as f:
            TOKEN_MAP = json.load(f)
    except Exception:
        TOKEN_MAP = {}

def http_json(url: str, method="GET", data=None, headers=None, timeout=25) -> Tuple[int, Any]:
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
            try:
                return resp.status, json.loads(body.decode("utf-8")) if body else None
            except Exception:
                return resp.status, body.decode("utf-8", "ignore")
    except error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return -1, str(e)

def tb_refresh_jwt() -> bool:
    """Refresh TB_JWT using TB_REFRESH; update env file if present."""
    global TB_JWT, TB_REFRESH
    if not TB_REFRESH:
        return False
    url = f"{TB_BASE}/api/auth/token"
    code, body = http_json(url, method="POST", data={"refreshToken": TB_REFRESH})
    if code == 200 and isinstance(body, dict) and body.get("token"):
        TB_JWT = body["token"]
        new_ref = body.get("refreshToken")
        if new_ref:
            TB_REFRESH = new_ref
        # persist to env file
        try:
            envfile = "/opt/xerxes-bridge/tb_jwt.env"
            with open(envfile, "w") as f:
                f.write(f'export TB_BASE="{TB_BASE}"\n')
                f.write(f'export TB_JWT="{TB_JWT}"\n')
                f.write(f'export TB_REFRESH="{TB_REFRESH}"\n')
        except Exception:
            pass
        print("[tb_sync] TB_JWT refreshed")
        return True
    print(f"[tb_sync] refresh failed {code}: {body}")
    return False

def ensure_device(jwt: str, name: str) -> str:
    # lookup by name
    code, body = http_json(
        f"{TB_BASE}/api/tenant/devices?deviceName={parse.quote(name)}",
        headers={"X-Authorization": f"Bearer {jwt}"},
    )
    if code == 200 and isinstance(body, dict) and body.get("id", {}).get("id"):
        return body["id"]["id"]
    # create if not exists
    payload = {"name": name, "type": DEVICE_TYPE, "deviceProfileName": DEVICE_PROFILE_NAME}
    code, body = http_json(f"{TB_BASE}/api/device", method="POST", data=payload,
                           headers={"X-Authorization": f"Bearer {jwt}"})
    if code == 200 and isinstance(body, dict) and body.get("id", {}).get("id"):
        return body["id"]["id"]
    raise RuntimeError(f"create device failed {code}: {body}")

def upsert_attributes_jwt(jwt: str, device_id: str, attrs: Dict[str, Any]) -> int:
    if not attrs:
        return 200
    url = f"{TB_BASE}/api/plugins/telemetry/DEVICE/{device_id}/attributes/SERVER_SCOPE"
    code, _ = http_json(url, method="POST", data=attrs, headers={"X-Authorization": f"Bearer {jwt}"})
    return code

def post_telemetry_jwt(jwt: str, device_id: str, data: List[Tuple[int, Dict[str, Any]]]) -> int:
    if not data:
        return 200
    url = f"{TB_BASE}/api/plugins/telemetry/DEVICE/{device_id}/timeseries/ANY"
    body = [{"ts": ts, "values": vals} for ts, vals in data if vals]
    if not body:
        return 200
    code, _ = http_json(url, method="POST", data=body, headers={"X-Authorization": f"Bearer {jwt}"})
    return code

def post_telemetry_token(token: str, values: Dict[str, Any]) -> int:
    url = f"{TB_BASE}/api/v1/{token}/telemetry"
    code, _ = http_json(url, method="POST", data=values, headers={})
    return code

def tb_ensure_device(token: str, uuid: str) -> str:
    """Ensures that Sensor-<uuid> exists in TB. Returns deviceId."""
    name = str(uuid)
    url = f"{TB_BASE}/api/tenant/devices?deviceName={name}"
    req = request.Request(url, method="GET",
                          headers={"X-Authorization": f"Bearer {token}"})

    try:
        with request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            # Device exists → return ID
            return body["id"]["id"]
    except:
        pass  # fallback → create device

    # Device does not exist → create it
    create_payload = {
        "name": name,
        "type": DEVICE_TYPE,
        "label": name,
        "deviceProfileName": DEVICE_PROFILE_NAME
    }

    req = request.Request(
        f"{TB_BASE}/api/tenant/devices",
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Authorization": f"Bearer {token}",
        }
    )

    with request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body["id"]["id"]

def main():
    # Musíme mať TB_JWT v prostredí (source tb_jwt.env)
    if not TB_JWT:
        raise SystemError("TB_JWT missing. Run: source /opt/xerxes-bridge/tb_jwt.env")

    # časové okno – napr. posledných LOOKBACK_MIN minút
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=LOOKBACK_MIN)

    # pripojenie na Mongo (používame MONGO_URI, DB_NAME, COLL_MEAS zhora)
    client = MongoClient(MONGO_URI)
    coll = client.get_database(DB_NAME).get_collection(COLL_MEAS)

    # filter na REAL dáta (origin=device, nie synthetic)
    REAL = {
        "ts": {"$gte": since},
        "meta.ingest.origin": "device",
        "$or": [
            {"is_synth": {"$exists": False}},
            {"is_synth": False},
        ],
    }

    uuids = list(coll.distinct("uuid", REAL))
    print(f"[tb_sync] UUIDs in last {LOOKBACK_MIN} min: {len(uuids)}")

    for u in uuids:
        q = dict(REAL)
        q["uuid"] = u

        docs = list(
            coll.find(q)
            .sort("ts", 1)
            .limit(500)
        )

        if not docs:
            continue

        # pripravíme sériu (ts_ms, values) pre TB
        series: List[Tuple[int, Dict[str, Any]]] = []
        for d in docs:
            ts = d.get("ts")
            if not isinstance(ts, dt.datetime):
                continue
            ts_ms = int(ts.timestamp() * 1000)

            values = d.get("measurements") or {}
            if not isinstance(values, dict) or not values:
                continue

            series.append((ts_ms, values))

        if not series:
            continue

        # ensure device v TB
        try:
            device_id = ensure_device(TB_JWT, str(u))
        except Exception as e:
            print(f"[tb_sync] ensure_device failed for uuid={u}: {e}")
            continue

        # pošleme telemetry
        try:
            code = post_telemetry_jwt(TB_JWT, device_id, series)
            print(
                f"[tb_sync] uuid={u} → device={device_id}, "
                f"frames={len(series)}, status={code}"
            )
        except Exception as e:
            print(f"[tb_sync] post_telemetry failed for uuid={u}: {e}")

if __name__ == "__main__":
    main()
