#!/usr/bin/env bash
set -euo pipefail
cd /opt/xerxes-bridge

echo "------------------------------------------------------------------"
echo "MONGO STORAGE HEALTH"
echo "------------------------------------------------------------------"

# disk pre / (tam máš aj Mongo)
/bin/df -h / | sed -n '1,2p'

# basic Mongo stats
/usr/bin/docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' \
  --authenticationDatabase admin --quiet <<'JS'
var dbx = db.getSiblingDB("xerxes");
print("dbstats:");
printjson(dbx.stats());
print("\nmeasurements count (24h):");
var since = new Date(Date.now()-24*60*60*1000);
print(dbx.measurements.countDocuments({ts:{$gte: since}}));
JS
