#!/usr/bin/env bash
set -euo pipefail
UUID="${1:-229252442470304}"
/usr/bin/docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --quiet --eval '
var since=new Date(Date.now()-60*60*1000);
var dbx=db.getSiblingDB("xerxes");
var cur=dbx.measurements.find(
  {uuid:"'$UUID'", "meta.ingest.synthetic":false, ts:{$gte: since}},
  {_id:0,ts:1, "meta.ingest.origin":1, measurements:1}
).sort({ts:-1}).limit(5);
cur.forEach(d=>printjson({ts:d.ts, origin:d.meta?.ingest?.origin, keys:Object.keys(d.measurements)}));'
