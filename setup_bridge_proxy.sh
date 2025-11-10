#!/usr/bin/env bash
set -euo pipefail

cd /opt/xerxes-bridge

echo "== ZÁLOHA docker-compose.yml =="
cp -a docker-compose.yml docker-compose.yml.bak.$(date +%Y%m%d-%H%M%S)

echo "== VYTVOR NGINX CONF =="
mkdir -p /opt/xerxes-bridge/nginx
cat > /opt/xerxes-bridge/nginx/bridge.conf <<'NGINX'
server {
  listen 80;
  server_name _;

  location / {
    proxy_pass http://xerxes-bridge:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
  }
}
NGINX

echo "== UPRAVA docker-compose.yml – doplnenie bridge-proxy =="
# Vytvoríme dočasný nový compose s proxy, zachováme tvoju službu 'xerxes-bridge'
cat > /opt/xerxes-bridge/docker-compose.yml <<'YAML'
services:
  xerxes-bridge:
    image: xerxes-bridge:v1.0.0-api-key
    container_name: xerxes-bridge-xerxes-bridge-1
    restart: unless-stopped

    environment:
      # --- AUTH pre Bridge ---
      PROJECT_API_KEY: "Silne+1"

      # --- ThingsBoard ---
      TB_HOST: "https://eu.thingsboard.cloud"
      TB_TIMEOUT_S: "5"
      TB_RETRIES: "2"
      TB_BACKOFF_MS: "300"

      # --- Token map ---
      TOKEN_MAP_PATH: "/app/token_map.json"

      # --- Časové/metadata polia ---
      TS_META_FIELD: "meta"
      TS_TIME_FIELD: "ts"

      # --- Mongo (PRIMÁRNY LOG) ---
      MONGO_URI: "mongodb://mongo:27017"
      MONGO_DB: "xerxes"
      MONGO_COL: "telemetry"

    ports:
      - "127.0.0.1:2080:8080"     # pôvodný (môže haprovať)
      - "127.0.0.1:28080:8080"    # priamy bind (možný docker-proxy glitch)

    volumes:
      - /opt/xerxes-bridge/token_map.json:/app/token_map.json:ro
      - /opt/xerxes-bridge/app.py:/app/app.py:ro

    networks:
      - mongo_default

  bridge-proxy:
    image: nginx:alpine
    container_name: bridge-proxy
    depends_on:
      - xerxes-bridge
    volumes:
      - /opt/xerxes-bridge/nginx/bridge.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - mongo_default
    ports:
      - "127.0.0.1:28081:80"    # STABILNÝ FRONT-DOOR (host:28081 -> nginx -> bridge)
    restart: unless-stopped

networks:
  mongo_default:
    external: true
YAML

echo "== VALIDÁCIA COMPOSE =="
docker compose config >/dev/null

echo "== DEPLOY stacku =="
docker compose up -d --force-recreate

echo "== ZOBRAZENIE BEŽIACYCH SLUŽIEB =="
docker compose ps

echo "== HEALTH test cez NGINX proxy (127.0.0.1:28081) =="
curl -sS http://127.0.0.1:28081/health | jq . || true

echo "== SMOKE POST cez NGINX proxy (127.0.0.1:28081) =="
UUID="229252442470304"
curl -sS -i "http://127.0.0.1:28081/bridge/ingest" \
  -H "API-Key: Silne+1" -H "Content-Type: application/json" \
  --data "{\"meta\":{\"uuid\":\"${UUID}\"},\"temp\":31.5,\"rh\":43.2}" | sed -n '1,60p' || true

echo "== IN-CONTAINER POST priamo do uvicorn (127.0.0.1:8080) =="
docker exec -it xerxes-bridge-xerxes-bridge-1 sh -lc '
python3 - <<PY
import http.client, json
c = http.client.HTTPConnection("127.0.0.1", 8080, timeout=5)
body = json.dumps({"meta":{"uuid":"'"${UUID}"'"},"temp":31.5,"rh":43.2})
c.request("POST","/bridge/ingest", body, {"Content-Type":"application/json","API-Key":"Silne+1"})
r = c.getresponse()
print("STATUS", r.status, r.reason)
print((r.read(200) or b"")[:200].decode("utf-8", "ignore"))
PY
'

echo "== HOTOVO =="
echo "Používaj stabilný front-door:  http://127.0.0.1:28081"
