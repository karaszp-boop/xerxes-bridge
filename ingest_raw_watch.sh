#!/usr/bin/env bash
set -euo pipefail
UUID="${1:-229252442470304}"
/usr/bin/docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --quiet --eval '
var dbx=db.getSiblingDB("xerxes");
dbx.ingest_raw.find({uuid:"'$UUID'"}, {ts:1,uuid:1,ip:1,body:1})
  .sort({ts:-1}).limit(5)
  .forEach(function(d){
    var keys = d.body?.values? Object.keys(d.body.values): (d.body?.measurements? Object.keys(d.body.measurements):[]);
    printjson({ts:d.ts, ip:d.ip, uuid:d.uuid, keys:keys, hasMeta: !!(d.body?.meta)});
  });'
