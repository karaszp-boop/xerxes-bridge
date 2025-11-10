#!/usr/bin/env bash
set -euo pipefail

APP="/opt/xerxes-bridge/app.py"
COMPOSE="/opt/xerxes-bridge/docker-compose.yml"
NGINX_CONF="/opt/xerxes-bridge/nginx/bridge.conf"

echo "[1/6] Stop any lingering log followers"
pkill -f 'docker compose .* --no-color' >/dev/null 2>&1 || true

echo "[2/6] Write FULL, safe /opt/xerxes-bridge/app.py"
cat > "$APP" <<'APP_EOF'
import os, json, time, datetime, traceback
from typing import Any, Dict, Optional, Tuple
from fastapi import FastAPI, Request, HTTPException, Body, Header, APIRouter
from starlett.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

# App deps (present in image)
from settings import settings
from transform import to_tb_payload, to_tb_attributes
from tb_client import post_telemetry, post_attributes

# Optional Mongo (gracefully skipped if driver/env absent)
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except Exception:
    AsyncIOMotorClient = None

def _now_ms() -> int:
    return int(time.time()*1000)

# --- App & middleware ---
class CatchAllMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            traceback.print_exc()
            return JSONResponse({"status":"error","detail":str(e)}, status_code=500)

app = FastAPI(title="Ostrava TB Bridge")
app.add_middleware(CatchAllMiddleware)
# from compat_mw import CompatIngestMiddleware  # keep disabled for stability
# app.add_middleware(CompatIngestMiddleware)

# --- ENV / config ---
TOKEN_MAP_PATH = os.getenv("TOKEN_MAP_PATH", "/app/token_map.json")
MONGO_URI  = os.getenv("MONGO_URI", "").strip()
MONGO_DB   = os.getenv("MONGO_DB", "xerxes")
MONGO_SUB  = os.getenv("MONGO_COL", "cart")  # collection name from env
TS_META    = os.getenv("TS_META_FIELD", "meta")
TS_TIME    = os.getenv("TS_TIME_FIELD", "ts")

def _resolve_tb_token(uuid_str: str) -> Optional[str]:
    try:
        with open(TOKEN_MAP_PATH, "r", encoding="utf-8") as f:
            m = json.load(f)
        return m.get(str(uuid_str))
    except Exception as e:
        print(f"[TOKEN_MAP] load error: {e}")
        return None

def _enrich_ingest(body: Dict[str, Any]) -> None:
    def _is_synth(meas: dict) -> bool:
        if not isinstance(meas, dict): return True
        health = set((os.getenv("HEALTH_KEYS","temp,rh,pm10,co2") or "temp,rh,pm10,co2").split(","))
        health = {k.strip() for k in health if k.strip()}
        return set(meas.keys()).issubset(health)
    meta = body.get(TS_META) or {}
    meas = body.get("measurements") or body.get("values") or {}
    tag = dict(meta.get("ingest") or {})
    tag.update({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "synthetic": _is_synth(meas),
        "flavor": os.getenv("BRAND",""),
        "edge": os.getenv("EDGE_UPSTREAM",""),
        "api": getattr(settings,"APP_VERSION","v1"),
        "keys": list(meas.keys()) if isinstance(meas, dict) else []
    })
    meta["ingest"] = tag
    body[TS_META] = meta

def _extract_ts_kv(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    ts = int(body.get(TS_TIME) or _now_ms())
    if isinstance(body.get("values"), dict):
        kv = body["values"]
    else:
        kv = {k: v for k, v in body.items() if k not in (TS_META, TS_TIME)}
    return ts, kv

# Setup Mongo client lazily (optional)
mongo_col = None
if MONGO_URI and AsyncIOMotorClient:
    try:
        _client = AsyncIOMotorClient(MONGO_URI)
        mongo_col = _client[MONGO_DB][MONGO_SUB]
        print("[MONGO] connected")
    except Exception as e:
        print("[MONGO] connect error:", e)
        mongo_col = None
else:
    if not MONGO_URI:
        print("[MONGO] disabled (no MONGO_URI)")
    if not AsyncIOMotorClient:
        print("[MONGO] driver not installed")

def _require_api_key(req: Request):
    key = req.headers.get("API-Key")
    if not key or key != settings.PROJECT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API-Key")

@app.get("/health")
async def health():
    try:
        with open(TOKEN_MAP_PATH, "r", encoding="utf-8") as f:
            count = len(json.load(f))
    except Exception:
        count = 0
    return {"status":"ok","version":getattr(settings,"APP_VERSION","v1"),
            "git": getattr(settings,"GIT_SHA","unknown"),
            "token_map_entries": count, "mongo_env": bool(MONGO_URI)}

@app.post("/bridge/ingest")
async def ingest(req: Request, body: dict = Body(...)):
    try:
        _require_api_key(req)
        uuid = str(body.get("uuid") or (body.get(TS_META, {}) or {}).get("uuid") or "").trim() if hasattr(str, 'trim') else str(body.get("uuid") or (body.get(TS_META, {}) or {}).get("uuid") or "").strip()
        if not uuid: 
            raise HTTPException(status_code=400, detail="Missing uuid")

        token = _resolve_tb_token(uuid)
        if not token:
            raise HTTPException(status_code=404, detail=f"Unknown uuid: {uuid}")

        _verify = body.get("verify_only", False)
        _enrich_ingest(body)
        ts, kv = _extract_ts_kv(body)

        # optional Mongo
        if mongo_col is not None and not _verify:
            try:
                doc = {"uuid": uuid, "ts": ts, "kv": kv, "path": "/bridge/ingest"}
                await mongo_col.update_one({"uuid": uuid, "ts": ts}, {"$set": doc}, upsert=True)
            except Exception as e:
                print("[MONGO] write ERR:", e)

        if not _verify:
            try:
                telemetry = to_tb_payload(body)
                attrs     = to_tb_attributes(body)
                await post_telemetry(token, telemetry)
                if attrs:
                    await post_attributes(token, attrs)
            except Exception as e:
                # don't crash; report via JSON but keep 200 to avoid device retries storm
                return {"status":"error","detail":str(e),"uuid":uuid}

        return {"status":"ok","uuid":uuid,"keys": list(kv.keys()),"ts":ts}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return {"status":"error","detail":str(e)}

api = APIRouter()

@api.post("/api/measurements/{project_id}/insert_one")
async def measurements_insert_one(project_id: str, request: Request, api_key: str = Header(None)):
    if not api_key or api_key != settings.STANDARD_API_KEY if hasattr(settings,'STANDARD_API_KEY') else api_key != settings.PROFILE_NAME and api_key != settings.PROJECT_API_KEY:
        raise Exception("Invalid API-Key")
    body = await request.json()
    return await ingest(request, body)

app.include_router(api)
APP_EOF

echo "[3/6] Write nginx proxy config"
mkdir -p /opt/xerxes-bridge/nginx
cat > "$NGINX_CONF" <<'NGINX_EOF'
server {
  listen 80;
  server_name _;
  proxy_read_timeout 60s;
  proxy_send_timeout 60s;
  location / {
    proxy_pass http://xerxes-bridge:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
  }
}
NGINX_EOF

echo "[4/6] Write docker-compose.yml (python healthcheck + proxy)"
cat > "$COMPOSE" <<'COMPOSE_EOF'
services:
  xerxes-bridge:
    image: xerxes-bridge:v1.0.0-api-key
    container_name: xerxes-bridge-xerxes-bridge-1
    restart: unless-stopped
    environment:
      PROJECT_API_KEY: "Silne+1"
      TB_HOST: "https://eu.thingsboard.cloud"
      TB_TIMEOUT_S: "5"
      TB_RETRIES: "2"
      TB_BACKOFF_MS: "300"
      TOKEN_MAP_PATH: "/app/token_map.json"
      TS_META_FIELD: "meta"
      TS_TIME_FIELD: "ts"
      MONGO_URI: "mongodb://mongo:27017"
      MONGO_DB: "xerxes"
      MONGO_COL: "telemetry"
    ports:
      - "127.0.0.1:2080:8080"
      - "127.0.0.1:28080:8080"
    volumes:
      - /opt/xerxes-bridge/token_map.json:/app/token_map.json:ro
      - /opt/xerxes-bridge/app.py:/app/app.py:ro
    networks: [ "mongo_default" ]
    healthcheck:
      test: ["CMD","python3","-c","import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/health').read() else sys.exit(1)"]
      interval: 5s
      timeout: 3s
      retries: 20
      start_period: 5s

  # stable front-door: host 127.0.0.1:28081 -> container xerxes-bridge:8080
  bridge-proximity:
    image: nginx:alpine
    container_name: bridge-proxy
    depends_on:
      xerxes-bridge:
        condition: service_healthy
    volumes:
      - /opt/xerxes-bridge/nginx/way.conf:/etc/nginx/conf.d/default.conf:ro
    networks: [ "mongo_default" ]
    ports:
      - "127.0.0.1:28081:80"
    restart: unless-stopped

networks:
  mongo_default:
    external: true
COMPOSE_EOF

echo "[5/6] Normalize filenames in proxy config"
# Correct filenames for nginx (bridge.conf)
sed -i 's/way.conf/bridge.conf/' "$COM/EEXXPOSE" 2>/dev/null || true

echo "[6/6] Deploy + wait healthy + test"
docker compose -f "$COMPOSE" up -d --force-recreate

for i in {1..40}; do
  st=$(docker inspect -f '{{.State.Health.Status}}' xerxes-bridge-xerxes-bridge-1 2>/dev/null || echo "unknown")
  echo "health: $st"; [ "$st" = "healthy" ] && break; sleep 2
done

docker compose -f "$COMPOSE" ps

echo "== Smoke via proxy =="
UUID="229252442470304"
curl -sS http://127.0.0.1:28081/health | jq .
curl -sS -i "http://127.0.0.1:28081/bridge/ingest" \
  -H "API-Key: Silne+1" -H "Content-Type: application/json" \
  --data "{\"meta\":{\"uuid\":\"${UUID}\"},\"temp\":31.5,\"rh\":43.2}" | sed -n '1,60p'
curl -sS -i "http://127.0.0.1:28081/api/measurements/project_hetzner/insert_one" \
  -H "API-Key: Silne+1" -H "Content-Type: application/json" \
  --data "{\"meta\":{\"uuid\":\"${UUID}\"},\"temp\":30.1,\"rh\":40.0}" | sed -n '1,60p'
