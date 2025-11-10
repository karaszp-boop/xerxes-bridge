#!/usr/bin/env python3
import json, os, sys
from pymongo import MongoClient, UpdateOne

MAP = "/opt/xerxes-bridge/token_map.json"
URI = f"mongodb://root:{os.environ.get('MONGO_PWD','ROOT_STRONG_PASSWORD')}@127.0.0.1:27017/?authSource=admin"

def main():
    m = json.load(open(MAP))
    items = (m.get("project_hetzner") or m)
    client = MongoClient(URI)
    col = client["xerxes"]["devices"]
    ops = [UpdateOne({"uuid": u}, {"$set": {"uuid": u, "tb": {"access_token": t}}}, upsert=True)
           for u,t in items.items()]
    if not ops: print("no entries"); return
    res = col.bulk_write(ops, ordered=False)
    print(f"upserted={len(res.upserted_ids)} matched={res.matched_count} modified={res.modified_count}")
if __name__ == "__main__":
    main()
