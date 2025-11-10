#!/usr/bin/env python3
import os, sys, json, urllib.request, urllib.error
from typing import Dict, Any
from pymongo import MongoClient, UpdateOne

TB_BASE = os.environ.get("TB_BASE", "https://eu.thingsboard.cloud")
TB_JWT  = os.environ.get("TB_JWT", "")            # raw token (BEZ "Bearer ")
TB_USER = os.environ.get("TB_USER", "")
TB_PASS = os.environ.get("TB_PASS", "")
PAGE_SZ = int(os.environ.get("TB_PAGE_SIZE", "100"))

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/?authSource=admin")
MONGO_DB  = os.environ.get("MONGO_DB", "xerxes")
COLL      = os.environ.get("MONGO_DEVICES_COL", "devices")

def tb_req(path:str, method="GET", data:Dict[str,Any]=None, auth=True):
    url = TB_BASE.rstrip("/") + path
    headers = {"Content-Type":"application/json"}
    if auth and TB_JWT:
        headers["X-Authorization"] = "Bearer " + TB_JWT
    req = urllib.request.Request(url, method=method, headers=headers)
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code} {url} :: {body}") from e

def ensure_jwt():
    global TB_JWT
    if TB_JWT: return TB_JWT
    if not TB_USER or not TB_PASS:
        raise SystemExit("Set TB_JWT or TB_USER/TB_PASS")
    resp = tb_req("/api/auth/login", method="POST", data={"username":TB_USER,"password":TB_PASS}, auth=False)
    TB_JWT = resp.get("token")
    if not TB_JWT: raise SystemExit("Failed to obtain TB JWT")
    return TB_JWT

def list_devices():
    ensure_jwt()
    page, has_next, out = 0, True, []
    while has_next:
        data = tb_req(f"/api/tenant/devices?pageSize={PAGE_SZ}&page={page}")
        out.extend(data.get("data", []))
        has_next = data.get("hasNext", False)
        page += 1
    return out

def get_access_token(device_id:str):
    try:
        creds = tb_req(f"/api/device/{device_id}/credentials")
        if isinstance(creds, dict):
            return creds.get("credentialsId")
    except Exception as e:
        print(f"[WARN] credentials for {device_id}: {e}", file=sys.stderr)
    return None

def main():
    devs = list_devices()
    print(f"[TB] fetched {len(devs)} devices")

    client = MongoClient(MONGO_URI)
    col = client[MONGO_DB][COLL]

    seen = set()
    ops  = []
    for d in devs:
        d_id   = (d.get("id") or {}).get("id")
        name   = d.get("name")
        label  = d.get("label")
        info   = d.get("additionalInfo") or {}
        # preferuj externalId; inak label; inak name
        base_uuid = (info.get("externalId") or label or name or d_id or "").strip()
        if not base_uuid:
            print(f"[SKIP] no uuid candidate for TB device {d_id} ({name})", file=sys.stderr)
            continue

        # dedupe: ak už existuje, pridaj -last6 TB id
        uuid = base_uuid
        if uuid in seen:
            uuid = f"{base_uuid}-{d_id[-6:] if d_id else 'dup'}"
        seen.add(uuid)

        tok = get_access_token(d_id)
        doc = {"uuid": uuid, "tb": {"id": d_id, "name": name, "label": label}}
        if tok: doc["tb"]["access_token"] = tok

        # DÔLEŽITÉ: uuid len v $setOnInsert, NIE v $set (inak Mongo conflict 40)
        ops.append(UpdateOne(
            {"uuid": uuid},
            {"$set": {"tb": doc["tb"]},
             "$setOnInsert": {"uuid": uuid}},
            upsert=True
        ))

    if ops:
        res = col.bulk_write(ops, ordered=False)
        print(f"[MONGO] upserted={len(res.upserted_ids)} matched={res.matched_count} modified={res.modified_count}")
    else:
        print("[MONGO] nothing to upsert")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[ERROR]", e, file=sys.stderr)
        sys.exit(2)
