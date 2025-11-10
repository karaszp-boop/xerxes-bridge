from motor.motor_asyncio import AsyncIOMotorClient
from settings import settings
from datetime import datetime, timezone

_client = None
_coll = None

async def init_mongo() -> bool:
    global _client, _coll
    if not settings.MONGO_URI:
        return False
    try:
        _client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=2000)
        db = _client[settings.MONGO_DB]
        await db.command("ping")
        _coll = db[settings.MONGO_COLL]
        print("[MONGO] init OK:", settings.MONGO_DB, settings.MONGO_COLL)
        return True
    except Exception as e:
        print("[MONGO] init FAIL:", e)
        _client = None; _coll = None
        return False

async def _ensure_mongo() -> bool:
    global _coll
    if _coll is not None:
        return True
    return await init_mongo()

async def insert_measurement(doc: dict) -> bool:
    global _coll
    try:
        if not await _ensure_mongo():
            print("[MONGO] SKIP insert (no client)")
            return False

        ts_field = getattr(settings, "TS_TIME_FIELD", "time")
        ts_val = doc.get("ts")
        if ts_val is None and "time" in doc:
            ts_val = doc["time"]

        if isinstance(ts_val, (int, float)):
            doc[ts_field] = datetime.fromtimestamp(float(ts_val)/1000.0, tz=timezone.utc)
        elif ts_val is None:
            doc[ts_field] = datetime.now(tz=timezone.utc)
        else:
            doc[ts_field] = ts_val

        mf = getattr(settings, "TS_META_FIELD", "meta")
        if mf and mf not in doc:
            doc[mf] = {}

        r = await _coll.insert_one(doc)
        print("[MONGO] insert OK:", r.inserted_id, "uuid=", doc.get("uuid"))
        return True
    except Exception as e:
        print("[MONGO] insert FAIL:", e)
        return False
