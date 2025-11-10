#!/usr/bin/env bash
set -euo pipefail
echo "=== ACCESS (last 60m) POST /bridge/ingest ==="
journalctl -u caddy --since "-60 min" --no-pager | grep 'POST /bridge/ingest' | tail -n 60 || true
echo
echo "=== BRIDGE (last 60m) ==="
/usr/bin/docker logs --since "$(date -u -d '-60 min' +%Y-%m-%dT%H:%M:%SZ)" xerxes-bridge-xerxes-bridge-1 2>&1 | egrep -i 'INGEST|ERROR' | tail -n 120 || true
echo
echo "=== MONGO (last 60m) 229... ==="
/usr/bin/docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --eval '
var since = new Date(Date.now()-60*60*1000);
var dbx=db.getSiblingDB("xerxes");
var uuid="229252442470304";
printjson(dbx.measurements.aggregate([
  {$match: {uuid:uuid, ts:{$gte: since}}},
  {$group: {_id:"$meta.ingest.synthetic", cnt:{$sum:1}}}
]).toArray());
var d=dbx.measurements.find({uuid:uuid, ts:{$gte: since}}).sort({ts:-1}).limit(5).toArray();
print("LAST docs:"); d.forEach(x=>printjson({ts:x.ts, origin: x.meta?.ingest?.origin, keys:Object.keys(x.measurements)}));
'
