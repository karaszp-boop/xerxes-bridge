import json
#!/usr/bin/env python3
import os, time, re
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.errors import PyMongoError

APP_VERSION = "bridge-1.0.8"

# --- ENV ---
PROJECT_API_KEY = os.getenv("PROJECT_API_KEY", "")
MONGO_URI       = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB        = os.getenv("MONGO_DB", "xerxes")
MONGO_COL       = os.getenv("MONGO_COL", "measurements")
TS_TIME_FIELD   = os.getenv("TS_TIME_FIELD", "ts")
TS_META_FIELD   = os.getenv("TS_META_FIELD", "meta")
REJECT_SYN      = os.getenv("REJECT_SYNTHETIC", "0") == "1"

# --- Mongo ---
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    mongo_client.admin.command("ping")
    db          = mongo_client[MONGO_DB]
    collection  = db[MONGO_COL]
    devices_col = db.get_collection("devices")
    print(f"[MONGO] connected; using {MONGO_DB}.{MONGO_COL}")
except Exception as e:
    print("[MONGO] init failed:", e)
    raise

# --- App ---
app = FastAPI(title="Xerxes Bridge", version=APP_VERSION)

@app.middleware("http")
async def _capture_raw_body(request, call_next):
    if request.url.path == "/bridge/ingest":
        try:
            raw = await request.body()
            try:
                request.state.raw_json = json.loads(raw.decode("utf-8"))
            except Exception:
                request.state.raw_json = {"_raw": raw.decode("utf-8","ignore")}
        except Exception:
            request.state.raw_json = None
    return await call_next(request)


async def _capture_raw_body(request, call_next):
    if request.url.path == "/bridge/ingest":
        try:
            raw = await request.body()
            try:
                request.state.raw_json = json.loads(raw.decode("utf-8"))
            except Exception:
                request.state.raw_json = {"_raw": raw.decode("utf-8","ignore")}
        except Exception:
            request.state.raw_json = None
    return await call_next(request)


async def _capture_raw_body(request, call_next):
    if request.url.path == "/bridge/ingest":
        try:
            raw = await request.body()
            try:
                request.state.raw_json = json.loads(raw.decode("utf-8"))
            except Exception:
                request.state.raw_json = {"_raw": raw.decode("utf-8","ignore")}
        except Exception:
            request.state.raw_json = None
    return await call_next(request)


async def _capture_raw_body(request, call_next):
    if request.url.path == "/bridge/ingest":
        try:
            raw = await request.body()
            try:
                request.state.raw_json = json.loads(raw.decode("utf-8"))
            except Exception:
                request.state.raw_json = {"_raw": raw.decode("utf-8","ignore")}
        except Exception:
            request.state.raw_json = None
    return await call_next(request)


async def _capture_raw_body(request, call_next):
    if request.url.path == "/bridge/ingest":
        try:
            raw = await request.body()
            try:
                request.state.raw_json = json.loads(raw.decode("utf-8"))
            except Exception:
                request.state.raw_json = {"_raw": raw.decode("utf-8","ignore")}
        except Exception:
            request.state.raw_json = None
    return await call_next(request)



# --- helpers ---
def _to_ms(ts: Optional[int]) -> int:
    if ts is None:
        return int(time.time() * 1000)
    try:
        v = int(ts)
        return v * 1000 if v < 10**11 else v
    except Exception:
        return int(time.time() * 1000)

def _client_ip(req: Request) -> str:
    xf = req.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    return (req.client.host or "")

def _is_private_ip(ip: str) -> bool:
    return (
        ip.startswith("127.") or ip == "localhost" or ip == "::1" or
        ip.startswith("10.") or ip.startswith("192.168.") or
        any(ip.startswith(f"172.{n}.") for n in range(16,32))
    )

def _normalize_uuid(u: str) -> str:
    if not isinstance(u, str): return str(u)
    m = re.match(r'(?i)sensor-(\d+)$', u.strip())
    return m.group(1) if m else u.strip()

def _meta_flat(meta: dict) -> dict:
    f = {}
    try:
        f["battery_v"] = ((meta or {}).get("power", {}) or {}).get("battery", {}).get("voltage")
    except Exception:
        pass
    f["fw_version"] = (meta or {}).get("version")
    m = (meta or {}).get("modem", {}) or {}
    f["csq"]  = m.get("signalQuality")
    return {k: v for k, v in f.items() if v is not None}

class IngestBody(BaseModel):
    uuid: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    measurements: Optional[Dict[str, Any]] = None
    values: Optional[Dict[str, Any]] = None
    ts: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None

@app.get("/health")
def health():
    mongo_client.admin.command("ping")
    return {"status":"ok","app":APP_VERSION,"db":MONGO_DB,"collection":MONGO_COL}

@app.post("/bridge/ingest", status_code=status.HTTP_201_CREATED)
async def ingest(body: IngestBody, request: Request):
    # -- uuid fallback (top-level or meta.uuid) --
    if (getattr(body, "uuid", None) in (None, "")) and isinstance(body.meta, dict):
        u = body.meta.get("uuid")
        if isinstance(u, (str,int)) and str(u).strip():
            body.uuid = str(u)
    if not getattr(body, "uuid", None):
        raise HTTPException(status_code=422, detail="uuid required (top-level or meta.uuid)")

    # -- uuid fallback (top-level or meta.uuid) --
    try:
        mongo_client.admin.command("ping")  # ensure Mongo client is ready
    except Exception:
        pass
    if (getattr(body, "uuid", None) in (None, "") ) and isinstance(body.meta, dict):
        u = body.meta.get("uuid")
        if isinstance(u, (str,int)) and str(u).strip():
            body.uuid = str(u)
    if not getattr(body, "uuid", None):
        raise HTTPException(status_code=422, detail="uuid required (top-level or meta.uuid)")

    # --- GUARDRAILS (B: allow meta-only=202) ---
    import os
    from fastapi.responses import JSONResponse
    ALLOW_META_ONLY = os.getenv("ALLOW_META_ONLY", "true").lower() == "true"
    has_meta = isinstance(body.meta, dict) and len(body.meta) >= 1
    has_vals = (isinstance(body.values, dict) and len(body.values) >= 1) or (isinstance(body.measurements, dict) and len(body.measurements) >= 1)
    # normalize: values -> measurements
    if isinstance(body.values, dict) and len(body.values) >= 1:
        body.measurements = body.values
    # default ts if missing
    if body.ts is None:
        import datetime as _dt
        body.ts = int(_dt.datetime.utcnow().timestamp() * 1000)
    # meta-only => 202 (no measurements write)
    if not has_vals and has_meta and ALLOW_META_ONLY:
        return JSONResponse(status_code=202, content={"status": "ok", "note": "meta-only accepted"})
    # nothing usable
    if not has_vals and not has_meta:
        return JSONResponse(status_code=422, content={"detail": "no measurements/values provided"})

    # API key
    api_key = request.headers.get("API-Key") or request.headers.get("Api-Key")
    if PROJECT_API_KEY and api_key != PROJECT_API_KEY:
        raise HTTPException(status_code=401, detail="invalid API-Key")

    # --- RAW LOG ---
    try:
        raw_db = mongo_client[MONGO_DB]["ingest_raw"]
        raw_doc = {
            "uuid": body.uuid,
            "ts": datetime.utcnow(),
            "ip": request.client.host if request.client else None,
            "headers": dict(request.headers),
            "body": (getattr(request.state, "raw_json", None) if True else {}),
        }
        raw_db.insert_one(raw_doc)
    except Exception as e:
        print("[WARN][RAW] failed to log ingest_raw:", e)

    # merge meraní
    merged: Dict[str, Any] = {}
    if isinstance(body.measurements, dict): merged.update(body.measurements)
    if isinstance(body.values, dict):       merged.update(body.values)
    if not merged:
        raise HTTPException(status_code=422, detail="no measurements/values provided")

    # ts → ISODate
    ts_ms = _to_ms(body.ts)
    ts_dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)

    # UUID normalizácia
    orig_uuid  = body.uuid
    canon_uuid = _normalize_uuid(str(body.uuid))

    # klasifikácia
    ip = _client_ip(request)
    has_meta   = isinstance(body.meta, dict) and len(body.meta) > 0
    has_values = (isinstance(body.values, dict) and len(body.values) >= 1) or (isinstance(body.measurements, dict) and len(body.measurements) >= 1)
    enough_keys= len(merged) >= 3
    is_local   = _is_private_ip(ip)
    is_real = has_meta or has_values
    # ensure meta.ingest.synthetic reflects REAL vs SYNTH
    try:
        _meta = body.meta if isinstance(body.meta, dict) else {}
        _ing = _meta.get("ingest") if isinstance(_meta.get("ingest"), dict) else {}
        _ing["synthetic"] = not is_real
        _meta["ingest"] = _ing
        body.meta = _meta
    except Exception:
        pass

    synthetic = (not is_real)
    # TS dokument
    doc = {"uuid": canon_uuid, TS_TIME_FIELD: ts_dt, "measurements": merged}

    # base meta
    meta = body.meta.copy() if isinstance(body.meta, dict) else {}
    meta.setdefault("ingest", {})
    meta["ingest"].update({
        "source_ip": ip,
        "synthetic": synthetic,
        "received_at": datetime.utcnow(),
        "uuid_original": str(orig_uuid),
        "uuid_canonical": str(canon_uuid),
        "origin": (request.headers.get("X-Bridge-Origin") or request.query_params.get("origin") or "device")
    })

    # safe payload snapshot – neukladáme celé meta znova, ale len vybrané časti
    clean_meta = body.meta.copy() if isinstance(body.meta, dict) else {}
    payload_meta = {
        "version": clean_meta.get("version"),
        "modem": clean_meta.get("modem"),
        "power": clean_meta.get("power"),
    }

    meta["payload"] = {
        "meta": payload_meta,
        "values": merged,  # spojené measurements/values
    }

    doc[TS_META_FIELD] = meta

    # Synthetic → len devices.last_seen, bez insertu
    if synthetic and REJECT_SYN:
        devices_col.update_one(
            {"uuid": canon_uuid},
            {
                "$setOnInsert": {"uuid": canon_uuid},
                "$set": {"last_seen_ts": ts_dt, "last_seen_ip": ip},
                "$addToSet": {"aliases": {"$each": [str(orig_uuid)]}}
            },
            upsert=True
        )
        # --- recompute (ensure values/measurements are visible here) ---
        has_values = (isinstance(body.values, dict) and len(body.values) >= 1) or (isinstance(body.measurements, dict) and len(body.measurements) >= 1)
        is_real = has_meta or has_values
        # synthetic only if NO meta AND NO values/measurements
        if (not has_meta) and (not has_values):
            return JSONResponse(status_code=202, content={"status":"accepted_synthetic","uuid": body.uuid})
    # Real → TS insert + devices update (safe $set bez None)
    try:
        res = collection.insert_one(doc)


        # --- keys_audit ---
        try:
            raw_vals = ((meta or {}).get("payload", {}) or {}).get("values")
            raw_keys = list((raw_vals or {}).keys()) if isinstance(raw_vals, dict) else []
            meas_keys = list(doc.get("measurements",{}).keys())
            missing = [k for k in raw_keys if k not in meas_keys]
            db.get_collection("keys_audit").insert_one({
                "ts": ts_dt,
                "uuid": canon_uuid,
                "doc_id": res.inserted_id,
                "raw_keys": raw_keys,
                "meas_keys": meas_keys,
                "missing_in_meas": missing
            })
        except Exception as e:
            print("[AUDIT][WARN] keys_audit failed:", e)

        flat = _meta_flat(meta)
        safe_set: Dict[str, Any] = {TS_META_FIELD: meta, "last_real_ts": ts_dt}
        if "battery_v" in flat:  safe_set["battery_v"]  = flat["battery_v"]
        if "fw_version" in flat: safe_set["fw_version"] = flat["fw_version"]
        if "csq" in flat:        safe_set["csq"]        = flat["csq"]

        devices_col.update_one(
            {"uuid": canon_uuid},
            {
                "$setOnInsert": {"uuid": canon_uuid},
                "$set": safe_set,
                "$addToSet": {"aliases": {"$each": [str(orig_uuid)]}}
            },
            upsert=True
        )

        print(f"[INGEST] inserted uuid={canon_uuid} real=True keys={list(merged.keys())[:16]} ip={ip} ts={ts_dt.isoformat()} id={res.inserted_id}")
        return {"status":"ok","uuid":canon_uuid,"id":str(res.inserted_id)}
    except PyMongoError as e:
        print("[INGEST][ERROR] mongo insert failed:", e)
        raise HTTPException(status_code=500, detail="mongo insert failed")
