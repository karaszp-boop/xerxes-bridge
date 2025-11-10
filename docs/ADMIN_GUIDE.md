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
