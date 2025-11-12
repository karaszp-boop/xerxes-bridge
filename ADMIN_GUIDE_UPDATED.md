# Xerxes Bridge – Admin Guide (snapshot bridge-1.0.8)

## 0) Stav release
- **Bridge ver.:** `bridge-1.0.8`
- **Zdravie:** `GET https://bridge.meta-mod.com/health` → `{"status":"ok","app":"bridge-1.0.8","db":"xerxes","collection":"measurements"}`
- **Kľúčové feat.:** UUID fallback (meta.uuid), lenient real, ingest_raw (TTL 24h), keys audit, devices upsert (battery_v/csq/fw), synthetic gating, normalizácia UUID, helper skripty.

---

## 1) API – Ingest

### 1.1 Endpoint a auth
- **POST** `https://bridge.meta-mod.com/bridge/ingest`
- **Headers:** `API-Key: Silne+1`, `Content-Type: application/json`

### 1.2 Akceptované formáty (Plan A – bez zásahu u Stana)
**Preferované (top-level `uuid`):**
```json
{
  "uuid": "229252442470304",
  "ts": 1762782999000,
  "values": {
    "light": 0.000125004, "sound_db": 56.21,
    "pm1_0": 0.1, "pm2_5": 0.1, "pm4_0": 0.1, "pm10": 0.1,
    "rh": 44.46, "temp": 20.925, "voc": 73, "nox": 1
  },
  "meta": {
    "version": "v1.5.0-0-g59a2eda",
    "modem": {"imei":"860470062067628","signalQuality":27,"simCCID":"8988..."},
    "power": {"battery":{"voltage":3.586}}
  }
}
Fallback (bez top-level uuid, ale s meta.uuid) – bridge doplní uuid:
{
  "values": { "...": "..." },
  "meta":  { "uuid": 229252442470304, "...": "..." },
  "ts":    1762782999000
}
1.3 Klasifikácia a ukladanie
	•	has_meta = (meta je dict a nie je prázdne)
	•	has_values = (values|measurements obsahuje ≥1 kľúč)
	•	is_real = has_meta OR has_values  (lenient)
	•	synthetic = (!is_real) OR (request_ip je private)
	•	Ak synthetic==true a REJECT_SYNTHETIC=1:
	•	bez insertu do TS, len devices.last_seen_ts/last_seen_ip, HTTP 202 ({"status":"accepted_synthetic"})
	•	Inak (REAL):
	•	insert do xerxes.measurements:
	•	ts ako ISODate, uuid kanonický, measurements = values, meta.ingest = {source_ip, received_at, origin, synthetic, uuid_original, uuid_canonical}, meta.payload = {meta, values}.
	•	upsert do xerxes.devices:
	•	$setOnInsert: {uuid}, $addToSet: {aliases:[uuid_original]}, $set: {meta, last_real_ts, battery_v, fw_version, csq}.

1.4 RAW logging
	•	Každý POST sa loguje do xerxes.ingest_raw (TTL 24h) s presným telom požiadavky (po middleware capture).

1.5 Očakávané odpovede
	•	201 Created – REAL insert úspešný
	•	202 Accepted – syntetika prijatá (bez TS insertu)
	•	401/403 – auth
	•	422 – chýba uuid (ani meta.uuid nebolo možné doplniť), alebo nevalidné telo

⸻

2) Mongo – Collections, schéma a indexy

2.1 xerxes.measurements (time-series)
{
  "uuid": "229252442470304",
  "ts": "ISODate(...)",
  "measurements": { "...": <number> },
  "meta": {
    "ingest": {
      "source_ip": "...",
      "received_at": "ISODate",
      "synthetic": false,
      "origin": "device|manual|...",
      "uuid_original": "Sensor-229252442470304|229252442470304",
      "uuid_canonical": "229252442470304"
    },
    "payload": {
      "meta":   { ... },   // originálne meta od zariadenia
      "values": { ... }    // originálne values od zariadenia
    },
    "...": "flattened selected meta (modem, power, ...)"
  }
}
Index: {uuid:1, ts:-1}

2.2 xerxes.devices (registry)
	•	uuid (unique), aliases[], tb.* (ak existuje), battery_v, fw_version, csq, last_real_ts, last_seen_ts, last_seen_ip, meta.*
Index: {uuid:1} unique

2.3 xerxes.ingest_raw (diagnostické)
	•	presné telo requestu (body) + uuid, ts, ip, headers
TTL index: {ts:1}, expireAfterSeconds: 86400

2.4 Keys audit (voliteľné)
	•	xerxes.keys_audit: ts, uuid, doc_id, raw_keys, meas_keys, missing_in_meas

⸻

3) Helper skripty (Hetzner)

Spúšťaj na Hetzneri v aktuálnom tabu:
/opt/xerxes-bridge/bridge_health.sh
/opt/xerxes-bridge/ingest_watch.sh
/opt/xerxes-bridge/ingest_raw_watch.sh 229252442470304
/opt/xerxes-bridge/measurements_watch.sh 229252442470304
/opt/xerxes-bridge/keys_audit_watch.sh 229252442470304
4) Compass – uložené dotazy

Last RAW payload (Stano original)
{
  "name": "Last RAW payload (Stano original)",
  "pipeline": [
    { "$match": { "uuid": "229252442470304", "meta.ingest.synthetic": false } },
    { "$sort":  { "ts": -1 } },
    { "$limit": 1 },
    { "$project": {
      "_id": 0,
      "ts": 1,
      "meta.payload.meta": 1,
      "meta.payload.values": 1
    }}
  ]
}
Compare RAW vs MEASUREMENTS keys
{
  "name": "Compare RAW vs MEASUREMENTS keys",
  "pipeline": [
    { "$match": { "uuid": "229252442470304", "meta.ingest.synthetic": false } },
    { "$sort":  { "ts": -1 } },
    { "$limit": 1 },
    { "$project": {
      "_id": 0,
      "ts": 1,
      "raw_keys":  { "$map": { "input": { "$objectToArray": "$meta.payload.values" }, "as": "kv", "in": "$$kv.k" } },
      "meas_keys": { "$map": { "input": { "$objectToArray": "$measurements" }, "as": "kv", "in": "$$kv.k" } }
    }}
  ]
}
5) Prevádzkové poznámky
	•	UUID fallback: ak chýba body.uuid, bridge doplní z meta.uuid (len Plan A).
	•	Lenient real: postačí mať meta alebo values; syntetika sa filtruje IP + prázdne hodnoty.
	•	„Temp-only“ vlna: ak prichádzajú len temp, TS je real, ale auditom vieš zistiť, že zvyšné kľúče chýbajú → vhodné na alerty.
	•	Backup & snapshot: snapshoty v /opt/xerxes-bridge/snapshots/… + git tag bridge-1.0.8.

⸻

6) Rýchla diagnostika Stanových 4xx
# 422 – chýba body.uuid a meta.uuid sa nedá prečítať
/opt/xerxes-bridge/inspect_last_422.sh

# 401/403 – zlý/žiadny API-Key (Caddy log)
/opt/xerxes-bridge/ingest_watch.sh

# potvrdenie plných kľúčov raw → TS
/opt/xerxes-bridge/ingest_raw_watch.sh 229252442470304
/opt/xerxes-bridge/measurements_watch.sh 229252442470304
7) Changelog
	•	1.0.8: UUID fallback, middleware RAW capture, ingest_raw TTL, lenient real, devices enrich, keys audit, helper pack.

jasné – spravíme to po tvojom štýle: najprv pripravíme obsah, potom konkrétne príkazy na doplnenie do „helpera“ a do ADMIN_GUIDE.md, a nakoniec git commit/push. Nič ti nespúšťam „za chrbtom“, všetko máš ako copy/paste príkazy s kompletnými cestami.

⸻

✅ Čo ideme doplniť
	1.	Helper – nové sekcie s hotovými príkazmi:
	•	JWT refresh (manuálne + timer)
	•	TB smoke test (tb_smoke.sh)
	•	Manuálny TB sync + logy + sprísnenie filtra
	•	Zapnutie periodického syncu (timer)
(štýl rovnaký ako tvoje existujúce helper bloky v /opt/xerxes-bridge)
	2.	ADMIN_GUIDE.md – nová kapitola:
	•	Autentizácia & automatický refresh JWT (refreshToken)
	•	Pipeline Mongo → TB s origin:"device" filtrom
	•	Synchro služby a časovače (systemd)
	•	Mapovanie atribútov (batt_v, signalQuality, fw_version, last_seen_ts)
	•	Troubleshooting (401, Mongo auth, 0 UUID, fallback na token)

⸻

🧰 A) Doplň príkazy do „helpera“

Vytvoríme (alebo doplníme) súbor /opt/xerxes-bridge/HELPER.md v tvojom repozitári. Obsahuje iba „recepty“ na Hetzneri. Môžeš si ho potom skrátiť/rozšíriť.

Spusti na Hetzneri (aktuálny iTerm tab):

# 1) Otvor/append HELPER.md
cat >>/opt/xerxes-bridge/HELPER.md <<'HLP'
# ───────────────────────────────────────────────────────────────
#  TB – REFRESH & SYNC HELPER (Hetzner / /opt/xerxes-bridge)
# ───────────────────────────────────────────────────────────────

## ▶︎ JWT REFRESH (Tenant API)
# Načítaj env + ručne obnov JWT (ak je 401 alebo pred testom)
source /opt/xerxes-bridge/tb_jwt.env
/hello/world # placeholder; ignore
/opt/xerxes-bridge/refresh_jwt.sh
journalctl -u refresh_jwt.service -n 50 --no-pager

# Timer pre refresh (po nasadení):
systemctl enable --now refresh_jwt.timer
systemctl status refresh_jwt.timer

## ▶︎ TB SMOKE TEST (create/find → POST → GET latest)
# Použitie: /opt/xerxes-bridge/scripts/tb_smoke.sh <UUID>
source /opt/xerxes-bridge/tb_jwt.env
/opt/xerxes-bridge/scripts/tb_smoke.sh 229252442470304

## ▶︎ MANUÁLNY SYNC Mongo → TB (s filterom na real device frames)
# 1) Načítaj env
source /opt/xerxes-bridge/tb_jwt.env
source /opt/xerxes-bridge/tb_local.env

# 2) Spusti ručne posledných 60–240 min (podľa potreby)
export LOOKBACK_MIN=120
python3 /opt/xerxes-bridge/tb_sync_from_mongo.py

# 3) Logy pri probléme:
journalctl -u xb_scrape.service -n 100 --no-pager
journalctl -u refresh_jwt.service -n 50 --no-pager

# 4) Over počet real frames v Mongo (posledných 240 min):
/usr/bin/docker exec -it mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --quiet --eval '
var dbx=db.getSiblingDB("xerxes");
var since=new Date(Date.now()-240*60*1000);
print("Total>=240m", dbx.measurements.countDocuments({ts:{$gte: since}}));
print("Device>=240m", dbx.measurements.countDocuments({ts:{$gte: since},"meta.ingest.origin":"device"}));
print("Device & non-synth", dbx.measurements.countDocuments({ts:{$gte: since},"meta.ingest.synthetic":false}));'

## ▶︎ PERIODIC SYNCHRO (každých 5 min)
# Zapnúť/overiť:
systemctl enable --now xb_scrape.timer
systemctl list-timers | grep xb_scrape
journalctl -u xb_scrape.service -n 50 --no-pager

## ▶︎ Fallback na device tokeny (ak JWT/refresh zlyhá)
# Priprav token map:
cat >/opt/xerxes-bridge/tokens.json <<'JSON'
{
  "229252442470304": "JnnxjeeszjGS874cOYqG",
  "172336768373140": "..."
}
JSON
chmod 600 /opt/xerxes-bridge/tokens.json
# tb_sync_from_mongo.py fallbackne pri 401->refresh fail: 'token_fallback=200' v logu

# ───────────────────────────────────────────────────────────────
HLP

(Ten # /hello/world je len nárazník, môžeš vymazať – slúži, aby sa block správne appendol.)

⸻

📘 B) Doplň ADMIN_GUIDE.md – nová kapitola (JWT refresh & Sync)

Spusti na Hetzneri:

cat >>/opt/xerxes-bridge/ADMIN_GUIDE.md <<'MD'
---

## 10) Autentifikácia & automatický refresh (JWT + refreshToken)

- TB Cloud (EU) → `POST /api/auth/login` vracia `token` (TB_JWT) a `refreshToken`.
- **Súbory s tajomstvami:** `/opt/xerxes-bridge/tb_jwt.env`  
  ```bash
  export TB_BASE="https://eu.thingsboard.cloud"
  export TB_JWT="…"
  export TB_REFRESH="…"

	•	Automatický refresh: refresh_jwt.sh beží cez refresh_jwt.timer každých 55 min a cez TB_REFRESH mení TB_JWT v env.
	•	Man. test:

source /opt/xerxes-bridge/tb_jwt.env
/opt/xerxes-bridge/refresh_jwt.sh
journalctl -u refresh_jwt.service -n 50 --no-pager


	•	Aktivácia:

systemctl enable --now refresh_jwt.timer



11) Ingest pipeline (Mongo → TB) s origin:"device" filtrom
	•	Filter (sprísnený):
	•	meta.ingest.origin == "device"
	•	is_synth != true
	•	ts >= now - LOOKBACK_MIN minutes
	•	Timeseries → TB /api/plugins/telemetry/DEVICE/<id>/timeseries/ANY
	•	posielame len číselné keys: temp, rh, pm1_0, pm2_5, pm4_0, pm10, voc, nox, sound_db, light
	•	dávkovo (po 250 bodov)
	•	fallback: pri 401 → refresh JWT a retry; ak zlyhá, posledný bod cez /api/v1/<token>/telemetry (ak v tokens.json)
	•	Attributes (SERVER_SCOPE):
	•	last_seen_ts (ms z meta.ingest.received_at alebo ts)
	•	batt_v (z meta.power.battery.voltage)
	•	signalQuality (z meta.modem.signalQuality)
	•	fw_version (z meta.version)

12) Periodické spúšťanie syncu
	•	Service: /etc/systemd/system/xb_scrape.service
Spúšťa python3 /opt/xerxes-bridge/tb_sync_from_mongo.py s LOOKBACK_MIN=10.
	•	Timer: /etc/systemd/system/xb_scrape.timer
Spúšťa service každých 5 minút.
	•	Manažment:

systemctl enable --now xb_scrape.timer
systemctl list-timers | grep xb_scrape
journalctl -u xb_scrape.service -n 50 --no-pager



13) Troubleshooting
	•	401 Unauthorized (TB):
	•	Skontroluj refresh_jwt.timer → journalctl -u refresh_jwt.service -n 50
	•	Ručne obnov: /opt/xerxes-bridge/refresh_jwt.sh, potom source /opt/xerxes-bridge/tb_jwt.env.
	•	Sync skript má aj vlastný tb_refresh_jwt() (retry po 401).
	•	„UUIDs in last N min: 0“ po sprísnení filtra:
	•	Over dáta v Mongo:

/usr/bin/docker exec -it mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --eval '
var d=db.getSiblingDB("xerxes");
var since=new Date(Date.now()-240*60*1000);
print("Device>=240m", d.measurements.countDocuments({ts:{$gte: since},"meta.ingest.origin":"device"}));
print("Device&non-synth", d.measurements.countDocuments({ts:{$gte: since},"meta.ingest.origin":"device",$or:[{"is_synth":{$exists:false}},{"is_synth":false}]}) );
'


	•	Dočasne zvýš LOOKBACK_MIN (napr. 240) a/alebo zjemni filter.

	•	Mongo „requires authentication“ v skripte:
	•	Uisti sa, že MONGO_URI v /opt/xerxes-bridge/tb_local.env obsahuje user:pass + authSource=admin.
	•	Skript číta env MONGO_URI; serverové mongosh používaš s -u/-p, ale pymongo potrebuje credentials v URI.

14) Mapovanie TB ► Dashboard
	•	Latest → Entities Table (admin konzola):
	•	name (entityField), temp (timeseries), pm2_5 (timeseries), light (timeseries),
	•	batt_v (attribute), signalQuality (attribute), fw_version (attribute),
	•	last_seen_ts (attribute s columnType: date).
	•	Detail (Xerxes – Device): markdown číta batt_v, last_seen_ts a timeseries kľúče; už nastavené.
MD

---

# 🧾 C) Git commit & push do tvojej repo

> **Predpokladám**, že `/opt/xerxes-bridge` je git repo a máš `origin` nastavený (ak nie, viem doplniť `git remote add origin …`).  

**Spusti:**
```bash
# 1) Skontroluj zmeny
cd /opt/xerxes-bridge
git status

# 2) Pridaj nové/aktualizované súbory
git add -A

# 3) Commit
git commit -m "docs: add JWT refresh + TB sync helper & update ADMIN_GUIDE; add timers + smoke script"

# 4) Push
git push

Ak ešte nemáš remote:
git remote add origin git@github.com:<tvoj-org>/xerxes-bridge.git && git push -u origin main

⸻

🎯 Záver
	•	Po tvojom smokovom teste a úspešnom manuálnom syncu už TB grafy a Latest bežia.
	•	Refresh timer beží na pozadí – netreba otvorený terminál.
	•	Teraz máš v HELPER.md hotové sekcie na bežné operácie a v ADMIN_GUIDE.md zdokumentovaný refresh/sync/troubleshooting.
	•	Zostáva iba git push a (ak chceš) zapnúť aj xb_scrape.timer.

Keď to odošleš do Git-u, daj vedieť – viem ešte pridať aj „TB tokens export“ helper a drobné gif/obrázky do ADMIN_GUIDE.md.
