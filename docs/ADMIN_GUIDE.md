Dobre, poďme to upratať a doplniť „dnešok“ rozumne, nie živelne 😊
Nižšie máš komplet zrevidovaný ADMIN_GUIDE.md – tak, ako by som ho videl v gite po dnešnom dni (Hetzner re-aktivácia, TB JWT refresh, tb_sync_from_mongo, repair skripty, duplicitné zariadenia v TB, atď.).

Môžeš ho celý skopírovať do ADMIN_GUIDE.md v repo.

⸻


# Xerxes Bridge – Admin Guide (bridge-1.0.8+sync)

Tento dokument popisuje architektúru a prevádzku `Xerxes Bridge` na Hetzner serveri (ubuntu-4gb-hel1-2) vrátane:

- ingestu meraní zo Stanových senzorov,
- ukladania do MongoDB,
- synchronizácie do ThingsBoard Cloud,
- automatického refreshu JWT,
- helper skriptov a troubleshooting postupov,
- post-incident záznamu po reaktivácii Hetzneru (24.11.2025).

---

## 0) Stav release

- **Bridge verzia:** `bridge-1.0.8+sync`
- **Healthcheck:**  
  `GET https://bridge.meta-mod.com/health`  
  → `{"status":"ok","app":"bridge-1.0.8","db":"xerxes","collection":"measurements"}`

- **Kľúčové vlastnosti:**
  - UUID fallback (ak chýba `body.uuid`, použije `meta.uuid`),
  - “lenient real” klasifikácia (stačí `meta` alebo `values`),
  - RAW logging do `xerxes.ingest_raw` (TTL 24h),
  - normalizácia UUID (canonical vs. original),
  - synthetic gating (syntetické dáta cez IP/obsah),
  - devices upsert (`battery_v`, `fw_version`, `csq`, `last_real_ts`),
  - TB sync: Mongo → ThingsBoard (len `origin=device`, non-synth),
  - automatický refresh TB JWT,
  - helper skripty na healthcheck, ingest watch, sync a repair.

---

## 1) API – Ingest (Bridge)

### 1.1 Endpoint a autentifikácia

- **Metóda:** `POST`
- **URL:** `https://bridge.meta-mod.com/bridge/ingest`
- **Headers:**
  - `API-Key: Silne+1`
  - `Content-Type: application/json`

### 1.2 Akceptovaný payload (Plan A – bez zásahu u Stana)

**Preferovaný formát – top-level `uuid`:**

```json
{
  "uuid": "229252442470304",
  "ts": 1762782999000,
  "values": {
    "light": 0.000125004,
    "sound_db": 56.21,
    "pm1_0": 0.1,
    "pm2_5": 0.1,
    "pm4_0": 0.1,
    "pm10": 0.1,
    "rh": 44.46,
    "temp": 20.925,
    "voc": 73,
    "nox": 1
  },
  "meta": {
    "version": "v1.5.0-0-g59a2eda",
    "modem": {
      "imei": "860470062067628",
      "signalQuality": 27,
      "simCCID": "8988..."
    },
    "power": {
      "battery": {
        "voltage": 3.586
      }
    }
  }
}

Fallback (bez top-level uuid, ale s meta.uuid)
Bridge doplní uuid z meta.uuid:

{
  "values": { "...": "..." },
  "meta":  { "uuid": 229252442470304, "...": "..." },
  "ts":    1762782999000
}

1.3 Klasifikácia a ukladanie (REAL vs. SYNTHETIC)

Interná logika:
	•	has_meta = (meta je dict a nie je prázdne)
	•	has_values = (values | measurements obsahuje ≥ 1 kľúč)
	•	is_real = has_meta OR has_values  (lenient real)
	•	synthetic = (!is_real) OR (request_ip je private)

Ak synthetic == true a REJECT_SYNTHETIC=1:
	•	bez insertu do measurements,
	•	update len do xerxes.devices (last_seen_ts, last_seen_ip),
	•	HTTP 202 Accepted → {"status":"accepted_synthetic"}.

Ak je frame REAL:
	•	insert do xerxes.measurements:
	•	ts ako ISODate,
	•	uuid_canonical = normalizované číslo,
	•	measurements = values,
	•	meta.ingest = { source_ip, received_at, origin, synthetic, uuid_original, uuid_canonical },
	•	meta.payload = { meta (originál), values (originál) }.
	•	upsert do xerxes.devices:
	•	$setOnInsert: { uuid }
	•	$addToSet: { aliases: [uuid_original] }
	•	$set: { meta, last_real_ts, battery_v, fw_version, csq }.

1.4 RAW logging
	•	Každý POST sa loguje do xerxes.ingest_raw s TTL 24h:
	•	RAW body,
	•	headers,
	•	uuid,
	•	ts,
	•	IP adresa.

1.5 Očakávané HTTP odpovede
	•	201 Created – REAL frame úspešne uložený.
	•	202 Accepted – syntetika akceptovaná (bez TS insertu).
	•	401 / 403 – problém s API-Key (Caddy/bridge auth).
	•	422 – chýba uuid a meta.uuid sa nedá použiť / nevalidné telo.

⸻

2) MongoDB – Collections, schéma a indexy

2.1 xerxes.measurements (time-series hlavná tabuľka)

Príklad dokumentu:

{
  "uuid": "229252442470304",
  "ts": ISODate("2025-11-24T08:41:11.455Z"),
  "measurements": {
    "temp": 25.1,
    "rh": 51.3,
    "pm2_5": 12.4,
    "pm10": 17.1,
    "light": 0.05,
    "sound_db": 60.6,
    "voc": 64,
    "nox": 1
  },
  "meta": {
    "ingest": {
      "source_ip": "...",
      "received_at": ISODate("..."),
      "synthetic": false,
      "origin": "device | manual | ...",
      "uuid_original": "Sensor-229252442470304 | 229252442470304",
      "uuid_canonical": "229252442470304"
    },
    "payload": {
      "meta":   { ... },   // originálne meta od zariadenia
      "values": { ... }    // originálne values od zariadenia
    },
    "...": "flattened selected meta (modem, power, ...)"
  }
}

Indexy:
	•	{ uuid: 1, ts: -1 } – primárny TS index.

2.2 xerxes.devices (registry zariadení)

Obsah:
	•	uuid (unique),
	•	aliases (["Sensor-229252442470304", "229252442470304", ...]),
	•	tb.* (ak existuje napojenie na ThingsBoard),
	•	battery_v,
	•	fw_version,
	•	csq,
	•	last_real_ts,
	•	last_seen_ts,
	•	last_seen_ip,
	•	meta.*.

Indexy:
	•	{ uuid: 1 } – unique.

2.3 xerxes.ingest_raw (diagnostické logy)
	•	presné telo requestu (body),
	•	uuid, ts,
	•	ip, headers.

Index:
	•	TTL index { ts: 1 }, expireAfterSeconds: 86400.

2.4 xerxes.keys_audit (voliteľné, audit kľúčov)
	•	ts,
	•	uuid,
	•	doc_id,
	•	raw_keys (zo meta.payload.values),
	•	meas_keys (z measurements),
	•	missing_in_meas.

⸻

3) Helper skripty (Hetzner)

Bežia na Hetzner serveri v /opt/xerxes-bridge.
Spúšťaj v aktuálnom iTerm tabu (root).

Skript	Účel
/opt/xerxes-bridge/bridge_health.sh	rýchly healthcheck bridge + Mongo
/opt/xerxes-bridge/ingest_watch.sh	posledných 60 min ingest (Caddy, bridge logs, Mongo)
/opt/xerxes-bridge/ingest_raw_watch.sh <uuid>	náhľad do ingest_raw pre konkrétny senzor
/opt/xerxes-bridge/measurements_watch.sh <uuid>	TS náhľad do measurements
/opt/xerxes-bridge/keys_audit_watch.sh <uuid>	porovnanie RAW vs. measurements kľúčov


⸻

4) Mongo Compass – uložené dotazy

4.1 Last RAW payload (Stano originál)

Pipeline (Compass):

[
  { "$match": { "uuid": "229252442470304", "meta.ingest.synthetic": false } },
  { "$sort":  { "ts": -1 } },
  { "$limit": 1 },
  { "$project": {
      "_id": 0,
      "ts": 1,
      "meta.payload.meta": 1,
      "meta.payload.values": 1
  } }
]

4.2 Compare RAW vs MEASUREMENTS keys

[
  { "$match": { "uuid": "229252442470304", "meta.ingest.synthetic": false } },
  { "$sort":  { "ts": -1 } },
  { "$limit": 1 },
  { "$project": {
      "_id": 0,
      "ts": 1,
      "raw_keys":  {
        "$map": {
          "input": { "$objectToArray": "$meta.payload.values" },
          "as": "kv",
          "in": "$$kv.k"
        }
      },
      "meas_keys": {
        "$map": {
          "input": { "$objectToArray": "$measurements" },
          "as": "kv",
          "in": "$$kv.k"
        }
      }
  } }
]


⸻

5) Prevádzkové poznámky
	•	UUID fallback:
Ak chýba body.uuid, bridge skúsi meta.uuid (Plan A – bez zásahu do FW/Stano).
	•	Lenient real:
Stačí mať meta alebo values; syntetika sa filtruje podľa IP + obsahu (prázdne values).
	•	„Temp-only“ vlna:
Ak chodia len temp, TS sa stále považuje za real.
Audity (keys_audit) ukážu, že chýbajú pm*, voc, nox → vhodné na alerty, nie na blokovanie.
	•	Backup & snapshot:
Snapshoty v /opt/xerxes-bridge/snapshots/… + git tagy bridge-1.0.8.

⸻

6) Rýchla diagnostika Stanových 4xx

6.1 HTTP 422 – chýba uuid / nevalidné body
	•	Skontrolovať posledné 422 v logu:

/opt/xerxes-bridge/inspect_last_422.sh


	•	Typicky: body nie je validný JSON alebo chýba uuid a meta.uuid.

6.2 HTTP 401 / 403 – zlý alebo chýbajúci API-Key
	•	Pozrieť Caddy log:

/opt/xerxes-bridge/ingest_watch.sh


	•	Overiť, čo posiela Stano (headers, endpoint).

6.3 Overenie plných kľúčov RAW → TS
	•	RAW:

/opt/xerxes-bridge/ingest_raw_watch.sh 229252442470304


	•	TS:

/opt/xerxes-bridge/measurements_watch.sh 229252442470304



⸻

7) ThingsBoard – Autonómny sync & JWT refresh

Od verzie bridge-1.0.8+sync je ThingsBoard pipeline autonómna:
	•	refreshuje TB JWT,
	•	periodicky syncuje Mongo → TB,
	•	má vlastný healthcheck.

7.1 Architektúra služieb (systemd)

Služba / Timer	Účel	Interval	Logy
refresh_jwt.service	obnovuje TB JWT + refresh token	podľa timeru	journalctl -u refresh_jwt.service
refresh_jwt.timer	spúšťa refresh_jwt.service	~6 hodín	systemctl status refresh_jwt.timer
xb_scrape.service	prenáša dáta Mongo → TB	one-shot	journalctl -u xb_scrape.service
xb_scrape.timer	spúšťa xb_scrape.service	každých 5 min	`systemctl list-timers

7.2 Kľúčové súbory

Cesta	Popis
/opt/xerxes-bridge/tb_jwt.env	TB JWT a refresh token
/opt/xerxes-bridge/tb_local.env	MONGO_URI a TB lokálne premenné
/opt/xerxes-bridge/refresh_jwt.sh	skript na obnovu TB JWT
/etc/systemd/system/refresh_jwt.{service,timer}	systemd jednotky pre JWT refresh
/etc/systemd/system/xb_scrape.{service,timer}	systemd jednotky pre TB sync
/opt/xerxes-bridge/tb_sync_from_mongo.py	hlavný sync skript Mongo → TB
/opt/xerxes-bridge/healthcheck_tb_v3.sh	TB healthcheck (auth + telemetry)

7.3 /opt/xerxes-bridge/tb_jwt.env (príklad)

Poznámka: žiadne export. Systemd používa formát KEY=VALUE.

TB_BASE=https://eu.thingsboard.cloud
TB_JWT=eyJhbGciOiJIUzUxMiJ9...
TB_REFRESH=eyJhbGciOiJIUzUxMiJ9...

7.4 /opt/xerxes-bridge/tb_local.env (príklad)

MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"
MONGO_DB="xerxes"
MONGO_COLL="measurements"

TB_DEVICE_TYPE="sensor"
TB_DEVICE_PROFILE="Xerxes Bridge – Sensor"
LOOKING_GLASS="on"


⸻

8) ThingsBoard sync (tb_sync_from_mongo.py)

8.1 Filter a výber dát
	•	Filtrovanie real frames:
	•	meta.ingest.origin == "device"
	•	meta.ingest.synthetic == false (resp. is_synth != true)
	•	ts >= now - LOOKBACK_MIN (minút)
	•	Timeseries → ThingsBoard:
	•	endpoint: /api/plugins/telemetry/DEVICE/{deviceId}/timeseries/ANY
	•	kľúče (numeric):
temp, rh, pm1_0, pm2_5, pm4_0, pm10, voc, nox, sound_db, light
	•	posiela sa v dávkach (napr. 250 bodov).
	•	Attributes (SERVER_SCOPE):
	•	last_seen_ts (ms z meta.ingest.received_at alebo ts),
	•	batt_v (z meta.power.battery.voltage),
	•	signalQuality (z meta.modem.signalQuality),
	•	fw_version (z meta.version),
	•	prípadne ďalšie meta fieldy.

8.2 Ensure device (tb_ensure_device)

Každý UUID z Mongo:
	•	skript najprv overí, že existuje device v TB (názov typicky Sensor-<uuid> alebo <uuid>),
	•	ak neexistuje, vytvorí device:
	•	name: Sensor-<uuid> alebo <uuid> podľa dohodnutej konvencie,
	•	type: sensor,
	•	deviceProfileName: Xerxes Bridge – Sensor.

Tým pádom sync:
	•	nevytvára duplicity, ak už device existuje,
	•	zabezpečí konzistentný naming.

⸻

9) Periodické spúšťanie syncu (xb_scrape.timer)
	•	Service: /etc/systemd/system/xb_scrape.service
→ spúšťa Python:

python3 /opt/xerxes-bridge/tb_sync_from_mongo.py

s predvoleným LOOKBACK_MIN=10 (alebo podľa nastavenia).

	•	Timer: /etc/systemd/system/xb_scrape.timer
→ spúšťa service každých 5 min.

Manažment:

systemctl enable --now xb_scrape.timer
systemctl list-timers | grep xb_scrape
journalctl -u xb_scrape.service -n 50 --no-pager


⸻

10) Troubleshooting TB (JWT, sync, Mongo auth)

10.1 401 Unauthorized (TB)
	•	skontroluj JWT refresh:

journalctl -u refresh_jwt.service -n 50 --no-pager


	•	ručne obnov JWT:

cd /opt/xerxes-bridge
./refresh_jwt.sh
source tb_jwt.env


	•	sync skript má internú funkciu tb_refresh_jwt() a pri 401 sa pokúsi refreshnúť token a retry.

10.2 “UUIDs in last N min: 0” po sprísnení filtra
	•	Over dáta v Mongo:

docker exec -it mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' --authenticationDatabase admin --eval '
var d=db.getSiblingDB("xerxes");
var since=new Date(Date.now()-240*60*1000);
print("Device>=240m", d.measurements.countDocuments({ts:{$gte: since},"meta.ingest.origin":"device"}));
print("Device&non-synth", d.measurements.countDocuments({ts:{$gte: since},"meta.ingest.origin":"device",$or:[{"is_synth":{$exists:false}},{"is_synth":false}]}) );
'


	•	dočasne zvýš LOOKBACK_MIN (napr. na 240) alebo zjemni filter.

10.3 “Mongo requires authentication” v skripte
	•	skontroluj, že MONGO_URI v tb_local.env obsahuje user/password:

MONGO_URI="mongodb://root:ROOT_STRONG_PASSWORD@127.0.0.1:27017/?authSource=admin"


	•	Python (pymongo) používa URI, nie shell login; to treba mať konzistentné.

⸻

11) Mapovanie TB → Dashboard

11.1 Entities Table (admin konzola)
	•	name (entity field, device name),
	•	Telemetry:
	•	temp,
	•	pm2_5,
	•	light,
	•	Attributes:
	•	batt_v,
	•	signalQuality,
	•	fw_version,
	•	last_seen_ts (typ = date).

11.2 Detailný markdown widget (Xerxes – Device)
	•	číta:
	•	batt_v,
	•	last_seen_ts,
	•	posledné temp, rh, pm*, voc, nox, sound_db, light.

Tento widget sa používa v TB dashboardoch na rýchlu diagnostiku jedného zariadenia.

⸻

12) Post-incident log – Hetzner & TB sync (24.11.2025)

Dátum: 24.11.2025
Incident:
	•	Hetzner server ubuntu-4gb-hel1-2 bol dočasne suspendovaný kvôli neuhradeným faktúram.
	•	Po reaktivácii:
	•	Bridge bežal, ale:
	•	TB JWT bol expirovaný (Token has expired),
	•	TB sync skript (tb_sync_from_mongo.py) padal na:
	•	401 (TB),
	•	latin-1 codec can't encode character '\u0161' (diakritika v názvoch),
	•	MONGO_URI nebolo v env pre sync skript (Unauthorized pri distinct),
	•	ThingsBoard nemal vytvorené devicy pre nové UUID (tb_sync hlásil NO_DEVICE),
	•	v TB sa vytvorili duplikátne/dev invalidné zariadenia (napr. Sensor-test>).

Riešenie (v skratke):
	1.	Obnovenie SSH prístupu na Hetzner (ssh hetzner).
	2.	Overenie docker kontajnerov – bridge a mongo bežali (docker ps).
	3.	Oprava MONGO_URI v tb_local.env a jeho export do env.
	4.	Nasadenie refresh_jwt.sh + refresh_jwt.timer → auto refresh TB_JWT.
	5.	Oprava tb_sync_from_mongo.py:
	•	pridanie tb_ensure_device() (create/find device v TB),
	•	fix encodingu hlavičiek (UTF-8 → latin-1 safe pre HTTP headers),
	•	fix na MONGO auth (MONGO_URI s user/password).
	6.	Zavedenie repair_tb.sh:
	•	refresh JWT,
	•	one-shot sync z Mongo → TB (LOOKBACK),
	•	healthcheck TB.
	7.	Zavedenie repair_devices_and_sync.sh:
	•	vytiahol všetky UUID z Mongo za posledných 24h,
	•	ensure TB devices pre každý UUID,
	•	spustil TB sync a healthcheck.
	8.	TB cleanup:
	•	manuálne odstránenie duplikátnych devices (napr. Sensor-test>, Sensor-<uuid> bez telemetrie),
	•	ponechané len reálne devices (s telemetriou a token mapou).
	9.	Validácia cez vlastný healthcheck:
	•	healthcheck_tb_v3.sh + porovnanie proti Stanovej DB,
	•	confirm, že Mongo aj TB majú rovnaký set UUID a fresh telemetry.

Výsledok:
	•	Bridge ingest funguje,
	•	Mongo má dáta from all active sensors,
	•	TB má správnych devices,
	•	TB sync beží autonómne (timer),
	•	healthcheck TB hlási konzistentné dáta.

⸻


---

Toto je jeden súvislý „uprataný“ `ADMIN_GUIDE.md`, ktorý zhrňuje aj dnešný incident na Hetzneri a jeho riešenie.  
Môžeš si ho:

- vložiť do `ADMIN_GUIDE.md` v repo,
- alebo rozdeliť na viaceré súbory, ak budeš chcieť (napr. zvlášť *TB Sync*, zvlášť *Incident log*).

Ak chceš, viem ti ešte pripraviť aj krátku **CHANGELOG** sekciu (1–2 riadky pre každú zmenu, vhodné do `CHANGELOG.md`).
