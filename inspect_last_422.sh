#!/usr/bin/env bash
set -euo pipefail
echo "==[ingest_raw] Last 5 payloads (ts, uuid, ip) =="
docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --quiet --eval '
db.getSiblingDB("xerxes").ingest_raw.find({}, {ts:1,uuid:1,ip:1,body:1}).sort({ts:-1}).limit(5).forEach(function(d){
  const keys = (d.body?.values? Object.keys(d.body.values):[]);
  const hasMeta = !!d.body?.meta && Object.keys(d.body.meta).length>0;
  printjson({ts:d.ts, uuid:d.uuid, ip:d.ip, keys:keys, hasMeta:hasMeta, rawBody:d.body});
});'
