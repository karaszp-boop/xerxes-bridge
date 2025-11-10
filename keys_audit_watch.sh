#!/usr/bin/env bash
set -euo pipefail
UUID="${1:-229252442470304}"
/usr/bin/docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --quiet --eval '
var dbx=db.getSiblingDB("xerxes");
dbx.keys_audit.find({uuid:"'$UUID'"}, {_id:0,ts:1,raw_keys:1,meas_keys:1,missing_in_meas:1})
  .sort({ts:-1}).limit(5).forEach(d=>printjson(d));'
