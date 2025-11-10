from compat_mw import CompatIngestMiddleware
from fastapi import FastAPI, Request, HTTPException, Body
from settings import settings
from transform import to_tb_payload, to_tb_attributes
from tb_client import post_telemetry, post_attributes
import json

app = FastAPI(title="Ostrava TB Bridge")

app.add_middleware(CompatIngestMiddleware)

# load token map
TOKEN_MAP = {}
try:
    with open(settings.TOKEN_MAP_PATH, "r") as f:
        TOKEN_MAP = json.load(f)
except Exception:
    TOKEN_MAP = {}

def require_api_key(req: Request):
    key = req.headers.get("API-Key")  # iba API-Key
    if not key:
        raise HTTPException(status_code=401, detail="Missing API-Key")
    if key != settings.PROJECT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API-Key")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "git": settings.GIT_SHA,
        "token_map_entries": len(TOKEN_MAP)
    }

@app.post("/bridge/ingest")
async def ingest(req: Request, body: dict = Body(...)):
    require_api_key(req)

    uuid = str(body.get("uuid") or (body.get("meta", {}).get("uuid") or "")).strip()
    if not uuid:
        raise HTTPException(status_code=400, detail="Missing uuid")

    token = TOKEN_MAP.get(uuid)
    if not token:
        raise HTTPException(status_code=404, detail=f"Unknown uuid: {uuid}")

    telemetry = to_tb_payload(body)
    attrs = to_tb_attributes(body)

    await post_telemetry(token, telemetry)
    if attrs:
        await post_attributes(token, attrs)


    # --- Auto Mongo insert ---
    try:
        doc = data if 'data' in locals() else payload if 'payload' in locals() else {}
        if isinstance(doc, dict):
            uuid = str(doc.get("uuid") or "").strip()
            meas = doc.get("measurements")
            if uuid and isinstance(meas, dict):
                db.measurements.insert_one({
                    "uuid": uuid,
                    "measurements": meas,
                    "meta": doc.get("meta"),
                })
                print(f"    except Exception as e:
        print(f"    return {"status": "ok", "uuid": uuid}
