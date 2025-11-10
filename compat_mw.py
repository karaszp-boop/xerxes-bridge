import os, json, datetime
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message, Receive
from typing import Dict, Any, Optional, Iterable, Tuple

def _health_keys() -> set:
    raw = os.getenv("HEALTH_KEYS", "temp,rh,pm10,co2")
    return {k.strip() for k in raw.split(",") if k.strip()}

_HEALTH = _health_keys()

def normalize_payload(data: dict) -> dict:
    """
    Legacy: {"meta":{"uuid":...}, "values":{...}}
    New:    {"uuid":..., "measurements":{...}, "meta":{...}}
    """
    if not isinstance(data, dict):
        return data
    if "meta" in data and isinstance(data.get("meta"), dict) and "values" in data:
        meta = data.get("meta") or {}
        vals = data.get("values") or {}
        uuid = str(meta.get("uuid") or meta.get("UUID") or "").strip()
        if uuid and isinstance(vals, dict):
            return {"uuid": uuid, "measurements": vals, "meta": meta}
    if "uuid" in data and "measurements" in data:
        if "meta" not in data or not isinstance(data.get("meta"), dict):
            data["meta"] = {}
        return data
    return data

def _is_synthetic(meas: dict) -> bool:
    if not isinstance(meas, dict):
        return True
    keys = set(meas.keys())
    return len(keys) <= len(_HEALTH) and keys.issubset(_HEALTH)

def _replace_header(scope_headers: Iterable[Tuple[bytes, bytes]], name: bytes, value: bytes) -> list:
    name_l = name.lower()
    out = []
    seen = False
    for k, v in scope_headers:
        if k.lower() == name_l:
            if not seen:
                out.append((name, value))
                seen = True
            # drop duplicates
        else:
            out.append((k, v))
    if not seen:
        out.append((name, value))
    return out

class CompatIngestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path or ""
        if request.method == "POST" and (path.startswith("/bridge/ingest") or path == "/ingest"):
            try:
                raw = await request.body()
                if raw:
                    parsed = json.loads(raw.decode("utf-8"))
                    fixed = normalize_payload(parsed)
                    if isinstance(fixed, dict):
                        meta = fixed.get("meta") or {}
                        meas = fixed.get("measurements") or {}

                        ingest = dict(meta.get("ingest") or {})
                        ingest.update({
                            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "synthetic": _is_synthetic(meas),
                            "flavor": os.getenv("BRIDGE_FLAVOR", ""),
                            "edge": os.getenv("EDGE_UPSTREAM", ""),
                            "api": os.getenv("APP_VERSION", "v1"),
                            "keys": list(meas.keys()) if isinstance(meas, dict) else []
                        })
                        meta["ingest"] = ingest
                        fixed["meta"] = meta

                        new_body = json.dumps(fixed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

                        # Preprogramuj receive() tak, aby odovzdal nové body handleru
                        async def _receive() -> Message:
                            return {"type": "http.request", "body": new_body, "more_body": False}
                        request._receive = _receive  # type: ignore[attr-defined]

                        # Uprav Content-Length hlavičku
                        scope = request.scope
                        scope["headers"] = _replace_header(scope.get("headers") or [],
                                                           b"content-length",
                                                           str(len(new_body)).encode("ascii"))
            except Exception as e:
                # middleware nikdy nesmie zastaviť ingest
                pass

        return await call_next(request)
