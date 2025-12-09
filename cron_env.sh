# Environment pre cron healthchecky

export TG_TOKEN=8461046916:AAGwZ84kLYeXIbPTFipi3bnZIlMdausUPLg
export TG_CHAT_ID=8395439676

export MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"
export MONGO_DB="xerxes"
export MONGO_COLL="measurements"

export TB_BASE="https://eu.thingsboard.cloud"

# default lookback pre monitor
export MON_LOOKBACK_MIN=180
#!/usr/bin/env bash
set -euo pipefail

cd /opt/xerxes-bridge

# TB env – nech je TB_JWT dostupný pre flow_table.py, tb_healthcheck atď.
set -a
source /opt/xerxes-bridge/tb_jwt.env
set +a

# (ostatné tvoje exporty – TG_TOKEN, TG_CHAT_ID, MONGO_URI, ...)
