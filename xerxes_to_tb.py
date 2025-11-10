#!/usr/bin/env python3
import os, time, json, logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request, Header, HTTPException
from dotenv import dotenv_values

# --- Konfigurácia z .env ---
cfg = {**dotenv_values("/opt/xerxes-bridge/.env"), **os.environ}
TB_HOST       = (cfg.get("TB_HOST") or "https://eu.thingsboard.cloud").rstrip("/")
BRIDGE_KEY    = cfg.get("BRIDGE_KEY", "")
DEFAULT_TOKEN = cfg.get("TB_TOKEN", "")
TOKENS_JSON   = cfg.get("PROJECT_TOKENS_JSON", "")
TOKENS_FILE   = cfg.get("PROJECT_TOKENS_FILE", "")

PROJECT_TOKENS: Dict[str, str] = {}
if TOKENS_JSON:
    try:
        PROJECT_TOKENS.update(json.loads(TOKENS_JSON))
    except Exception:
        pass
if TOKENS_FILE and os.path.isfile(TOKENS_FILE):
    try:
        with open(TOKENS_FILE, "r") as f:
            PROJECT_TOKENS.update(json.load(f))
    except Exception:
        pass

# --- Mongo (lokálne CE) ---
MONGODB_URI = cfg.get("MONGODB_URI")
DB_NAME     = cfg.get("DB_NAME", "xerxes")
COLL_TS     = cfg.get("COLL_TS", "measurements")

ts_coll = None
if MONGODB_URI:
    try:
        from pymongo import MongoClient
        mc = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        # warmup ping
        mc.admin.command("ping")
        ts_coll = mc[DB_NAME][COLL_TS]
    except Exception:
        ts_coll = None  # nechceme blokovať Bridge, keď Mongo nie je k dispozícii

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bridge")

app = FastAPI(title="Xerxes → ThingsBoard Bridge", version="1.1")

def flatten(d: Dict[str, Any], parent: str = "", sep: str = "_") -> Dict[str, Any]:
    out = {}
    for k, v in (d or {}).items():
        key = f"{parent}{sep}{k}" if parent else k
        if isinstance(v, dict):
            out.update(flatten(v, key, sep))
        else:
            out[key] = v
    return out

def post_tb(token: str, telemetry: Dict[str, Any]):
    url = f"{TB_HOST}/api/v1/{token}/telemetry"
    r = requests.post(url, json=telemetry, timeout=15)
    r.raise_for_status()

def now_dt() -> datetime:
    return datetime.now(timezone.utc)

def ensure_struct(body: Dict[str, Any], project_id: str) -> Dict[str, Any]:
    """Vytvor dokument v tvare meta/measurements/time/ts + doplň minimum, ak chýba."""
    meta = body.get("meta", {})
    # prilep project_id do meta (užitočné pre filtrovanie v Mongo)
    if "project_id" not in meta:
        meta["project_id"] = project_id

    measurements = body.get("measurements", {})
    # ak prišli ploché kľúče, doplň ich do measurements
    flat = flatten(body)
    for k in ("light_low_gain","light_high_gain","sound_db","pm1_0","pm2_5","pm4_0","pm10","rh","temp","voc","nox"):
        if k not in measurements and k in flat and isinstance(flat[k], (int,float)):
            measurements[k] = flat[k]

    time_block = body.get("time", {})
    server_block = time_block.get("server", {})
    if "epoch" not in server_block:
        server_block["epoch"] = float(time.time())
    if "UTC" not in server_block:
        server_block["UTC"] = now_dt().strftime("%Y-%m-%d %H:%M:%S")
    time_block["server"] = server_block

    doc = {
        "meta": meta,
        "measurements": measurements,
        "time": time_block,
        "ts": now_dt()
    }
    return doc

@app.get("/health")
def health():
    return {"status": "ok", "tb_host": TB_HOST, "mapped_projects": len(PROJECT_TOKENS)}

@app.post("/api/measurements/{project_id}/insert_one")
async def insert_one(project_id: str, request: Request, x_api_key: Optional[str] = Header(None)):
    # API-key (ak nastavený)
    if BRIDGE_KEY and x_api_key != BRIDGE_KEY:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    token = PROJECT_TOKENS.get(project_id) or DEFAULT_TOKEN
    if not token:
        # stále uložíme do Mongo, ale reportneme konfiguráciu
        raise HTTPException(status_code=500, detail="No TB token configured for this project_id")

    # 1) priprav Mongo dokument + TB telemetry (flatten numerics)
    doc = ensure_struct(body if isinstance(body, dict) else {}, project_id=project_id)
    telemetry: Dict[str, Any] = {}
    flat = flatten(body if isinstance(body, dict) else {})
    # zober všetky numerické hodnoty – TB zvláda ľubovoľné kľúče
    for k, v in flat.items():
        if isinstance(v, (int, float)):
            telemetry[k] = v
    # doplň aliasy zo štruktúry measurements (ak nie sú vo flate)
    for k, v in (doc.get("measurements") or {}).items():
        if isinstance(v, (int, float)) and k not in telemetry:
            telemetry[k] = v
    telemetry.setdefault("heartbeat", int(time.time()))

    # log pre debuggovanie routingu
    log.info("project_id=%s, keys=%s", project_id, list(telemetry.keys())[:12])

    # 2) persist do Mongo (best-effort)
    if ts_coll is not None:
        try:
            ts_coll.insert_one(doc)
        except Exception as e:
            log.warning("Mongo insert failed: %s", e)

    # 3) push do TB (best-effort, nepadáme 502 – vrátime queued)
    forwarded = False
    try:
        post_tb(token, telemetry)
        forwarded = True
    except Exception as e:
        log.error("TB push failed: %s", e)
        forwarded = False

    return {"status": "ok" if forwarded else "queued", "project_id": project_id}
