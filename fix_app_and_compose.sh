#!/usr/bin/env bash
set -euo pipefail

APP=/opt/xerxes-bridge/app.py
COMPOSE=/opt/xerxes-bridge/docker-compose.yml

echo "== write full stable app.py =="
cat > "$APP" <<'EOF_APP'
import os, json, time, datetime, traceback
from typing import Any, Dict, Optional, Tuple
from fastapi import FastAPI, Request, HTTPException, Body, Header, APIRouter
from starlette.middleware.base import BaseHTTPMiddleware

from settings import settings
from transform import to_tb_payload, to_tb_attributes
from tb_client import post_telemetry, post_attributes
# from compat_mw import CompatIngestMiddleware  # keep off

class CatchAllMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            traceback.print_exc()
            from fastapi.responses import JSONResponse
            return JSONResponse({"status":"error","detail":str(e)}, status_code=500)

app = FastAPI(title="Ostrava TB Bridge")
app.add_middleware(CatchAllMiddleware)
# app.add_middleware(CompatIngestMiddleware)

TOKEN_MAP_PATH = os.getenv("TOKEN_MAP_PATH", "/app/token_map.json")
MONGO_URI  = os.getenv("MONGO_URI", "").strip()
MONGO_DB   = os.getenv("MONGO_DB", "xerxes")
MONGO_COL  = os.getenv("MONGO_COL", "telemetry")
TS_META    = os.getenv("TS_META_FIELD", "meta")
TS_TIME    = os.getenv("TS_TIME_FIELD", "ts")

def _now_ms() -> int:
    return int(time.time()*1000)

def _resolve_tb_token(uuid_str: str) -> Optional[str]:
    try:
        with open(TOKEN_MAP_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get(uuid_str)
    except Exception as e:
        print(f"[TOKEN_MAP] load error: {e}")
        return None

def require_api_key(req: Request):
    key = req.headers.get("API-Key")
    if not key:
        raise HTTPException(status_code=401, detail="Missing API-Key")
    if key != settings.PROJECT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API-Key")

@app.get("/health")
async def health():
    try:
        with open(TOKEN_MAP_PATH, "r", encoding="utf-8") as f:
            tcount = len(json.load(f))
    except Exception:
        tcount = 0
    return {
        "status": "ok",
        "version": getattr(settings, "APP_VERSION", "v1.0.0-api-key"),
        "git": getattr(settings, "GIT_SHA", "unknown"),
        "token_map_entries": tcount,
        "mongo_env": bool(MONGO_URI),
    }

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except Exception:
    AsyncIOMotorClient = None

mongo_client = None
mongo_col = None
if MONGO_URI and AsyncIOMotorClient:
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        mongo_col = mongo_client[MONGO_DB][MONGO_COL]
        print("[MONGO] connected")
    except Exception as e:
        print(f"[MONGO] connect ERR: {e}")
        mongo_client = None
        mongo_col = None
else:
    if not MONGO_URI: print("[MONGO] disabled (no MONGO_URI)")
    if not AsyncIOMotorClient: print("[MONGO] disabled (motor not installed)")

def _extract_ts_and_kv(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    ts = int(body.get(TS_TIME) or _now_ms())
    if isinstance(body.get("values"), dict):
        kv = body["values"]
    else:
        kv = {k: v for k, v in body.items() if k not in (TS_META, TS_TIME)}
    return ts, kv

def _enrich_ingest(body: Dict[str, Any]) -> None:
    def _ingest_is_synthetic(meas: dict) -> bool:
        if not isinstance(meas, dict): return True
        health = set((os.getenv("HEALTH_KEYS","temp,rh,pm10,co2") or "temp,rh,pm10,co2").split(","))
        health = {k.strip() for k in health if k.strip()}
        keys = set(meas.keys())
        return len(keys) <= len(health) and keys.issubset(health)
    meta = body.get(TS_META) or {}
    meas = body.get("measurements") or body.get("values") or {}
    tag  = dict(meta.get("ingest") or {})
    tag.update({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "synthetic": _ingest_is_synthetic(meas),
        "flavor": os.getenv("BRIDGE_FLAVOR",""),
        "edge": os.getenv("EDGE_UPSTREAM",""),
        "api": os.getenv("APP_VERSION","v1"),
        "keys": list(meas.keys()) if isinstance(meas, dict) else []
    })
    meta["ingest"] = tag
    body[TS_META] = meta

@app.post("/bridge/ingest")
async def ingest(req: Request, body: dict = Body(...)):
    try:
        require_api_key(req)
        uuid = str(body.get("uuid") or (body.get(TS_META, {}) or {}).get("uuid") or "").strip()
        if not uuid:
            raise HTTPException(status_code=400, detail="Missing uuid")

        token = _resolve_tb_token(uuid)
        if not token:
            raise HTTPException(status_code=404, detail=f"Unknown uuid: {uuid}")

        _enrich_ingest(body)
        ts, kv = _extract_ts_and_kv(body)

        # Mongo (best-effort) – explicit None
        if mongo_col is not None:
            try:
                doc = {"uuid": uuid, "ts": ts, "kv": kv, "path": "/bridge/ingest"}
                await mongo_col.update_one({"uuid": uuid, "ts": ts}, {"$set": doc}, upsert=True)
            except Exception as e:
                print(f"[MONGO] write ERR uuid={uuid}: {e}")

        telemetry = to_tb_payload(body)
        attrs     = to_tb_attributes(body)
        await post_telemetry(token, telemetry)
        if attrs:
            await post_attributes(token, attrs)

        keys = list((telemetry.get("values") or telemetry).keys())
        return {"status":"ok","uuid":uuid,"keys":keys,"ts":ts}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return {"status":"error","detail":str(e)}

router = APIRouter()

@router.post("/api/measurements/{project_id}/insert_one")
async def measurements_insert_one(project_id: str, request: Request, api_key: str = Header(None)):
    if not api_key or api_key != settings.PROJECT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API-Key")
    body = await request.json()
    return await ingest(request, body)

app.include_router(router)
EOF_APP

echo "== syntax-check app.py =="
python3 - <<'PY'
import py_compile, sys
py_compile.compile('/opt/xerxes-bridge/app.py', doraise=True)
print('app.py syntax OK')
PY

echo "== ensure python healthcheck =="
python3 - <<'PY'
from ruamel.yaml import YAML
p="/opt/xerxes-bridge/docker-compose.yml"
yaml=YAML(); data=yaml.load(open(p))
data['services']['xerxes-bridge']['healthcheck']={
 "test":["CMD","python","-c","import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/health').read() else sys.exit(1)"],
 "interval":"5s","timeout":"3s","retries":20,"start_period":"5s"}
yaml.dump(data, open(p,'w'))
print("healthcheck set to python")
PY 2>/dev/null || true

echo "== redeploy =="
cd /opt/xerxes-bridge
docker compose up -d --build --force-recreate
for i in {1..40}; do
  st=$(docker inspect -f '{{.State.Health.Status}}' xerxes-bridge-xerxes-bridge-1 2>/dev/null || echo "unknown")
  echo "Health: $st"
  [ "$st" = "healthy" ] && break
  sleep 2
done
docker compose ps

echo "== proxy tests =="
curl -sS http://127.0.0.1:28081/health | jq .
UUID="229252442470304"
curl -sS -i "http://127.0.0.1:28081/bridge/ingest" \
  -H "API-Key: Silne+1" -H "Content-Type: application/json" \
  --data "{\"meta\":{\"uuid\":\"${UUID}\"},\"temp\":31.5,\"rh\":43.2}" | sed -n '1,80p'
PROJECT_ID="project_hetzner"
curl -sS -i "http://127.0.0.1:28081/api/measurements/${PROJECT_ID}/insert_one" \
  -H "API-Key: Silne+1" -H "Content-Type: application/json" \
  --data "{\"meta\":{\"uuid\":\"${UUID}\"},\"temp\":30.1,\"rh\":40.0}" | sed -n '1,80p'
