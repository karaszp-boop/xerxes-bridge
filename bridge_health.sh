#!/usr/bin/env bash
set -euo pipefail
echo "==[1/4] BRIDGE LOCAL /health =="
curl -s -o - -w '\nHTTP=%{http_code}\n' http://127.0.0.1:28080/health || true
echo
echo "==[2/4] BRIDGE PUBLIC /health =="
curl -s -o - -w '\nHTTP=%{http_code}\n' https://bridge.meta-mod.com/health || true
echo
echo "==[3/4] BRIDGE LOGS (last 50 lines, health/errors) =="
docker logs --since "$(date -u -d '-5 min' +%Y-%m-%dT%H:%M:%SZ)" xerxes-bridge-xerxes-bridge-1 2>&1 | egrep -i 'health|ERROR|Traceback' || true
echo
echo "==[4/4] MONGO PING =="
docker exec -i mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --quiet --eval 'db.runCommand({ping:1})' || true
