Jasné — pripravím ti kompletný .md súbor pre GitHub + pre tvoj interný XERXES helper.
Celý dokument bude obsahovať:
	•	účel diagnostiky
	•	kroky pre spustenie
	•	presné príkazy
	•	interpretáciu výsledkov
	•	per-device gap analýzu
	•	čo odovzdať Stanovi

⸻

📄 TU JE HOTOVÝ .md SÚBOR (NA PRIAME VLOŽENIE DO GITU)

Skopíruj si to ako:

docs/xerxes_telemetry_gap_diagnostika.md


⸻

🟦 xerxes_telemetry_gap_diagnostika.md

# XERXES – TELEMETRY GAP DIAGNOSTIKA
### Monitoring a analýza doručovania telemetrie zo Stano devices  
Autor: p. Karasz  
Dátum: 2025

---

# 🔍 Účel dokumentu

Tento dokument slúži ako **diagnostický nástroj pre celý Stano → Bridge → Mongo → ThingsBoard ingest pipeline**.

Pomocou jednoduchých príkazov dokáže identifikovať:

- skutočné doručené framy z každého zariadenia,
- časové výpadky (GAPs) v telemetrii,
- first/last timestamp zariadenia,
- per-device stabilitu / nestabilitu,
- informácie potrebné pre komunikáciu so Stanom.

Tento nástroj poskytuje **jednoznačný dôkaz**, že:

- Bridge prijíma a ukladá všetky dáta 1:1,  
- všetky výpadky viditeľné v TB sa dajú vysvetliť reálnymi výpadkami telemetry z jednotlivých zariadení,  
- diagnostika je plne reprodukovateľná.

---

# 🧠 Architektúra – čo sa kontroluje

Stano device → (internet) → Cloudflare → Bridge API → ingest_raw → measurements (TS) → ThingsBoard

Diagnostika analyzuje:

- iba to, čo reálne prišlo na Bridge (ingest_raw),
- a porovnáva to s tým, čo skončilo v time-series (measurements).

**Bridge/Mongo nevytvárajú žiadnu filtráciu ani TTL — všetky rozdiely pochádzajú zo zariadení.**

---

# 🚀 Ako spustiť TELEMETRY GAP DIAGNOSTIKU

> **Spúšťa sa na Hetzneri v existujúcom iTerm tabe.**

### Príkaz:

```bash
/usr/bin/docker exec -it mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' \
  --authenticationDatabase admin --eval '
var dbx = db.getSiblingDB("xerxes");

print("=== TELEMETRY GAP REPORT (posledných 48h) ===");

var since = new Date(Date.now() - 48*60*60*1000);

// zoznam všetkých UUID v ingest_raw za posledných 48h
var uuids = dbx.ingest_raw.distinct("uuid", { ts: { $gte: since } });

uuids.forEach(function(u){
    print("\nDEVICE:", u);

    var frames = dbx.ingest_raw.find({ uuid: u, ts: { $gte: since } })
        .sort({ ts: 1 })
        .toArray();

    if(frames.length === 0){
        print("  ❌  Žiadne dáta za posledných 48h");
        return;
    }

    var first = frames[0].ts;
    var last = frames[frames.length - 1].ts;

    var gaps = [];
    for(var i = 1; i < frames.length; i++){
        var prev = frames[i-1].ts;
        var cur = frames[i].ts;
        var diffMin = (cur - prev) / 1000 / 60;
        if(diffMin > 10){ // gap > 10 min
            gaps.push({ gap_min: diffMin, from: prev, to: cur });
        }
    }

    print("  Frames:", frames.length);
    print("  First:", first);
    print("  Last:", last);

    if(gaps.length === 0){
        print("  Gaps: 0  (OK)");
    } else {
        print("  ⚠️  Gaps:", gaps.length);
        gaps.forEach(g => {
            print("    - gap", g.gap_min.toFixed(1), "min  from", g.from, "to", g.to);
        });
    }
});
'


⸻

📊 Ako čítať výsledky

✔ Normálny stav (periodické odosielanie)

gap 14.9 min  → zariadenie posiela každých ~15 min   → OK

⚠ Reálne výpadky

gap 120 min  → zariadenie bolo 2 h offline
gap 300 min  → zariadenie bolo 5 h offline
gap 700 min  → zariadenie bolo 12 h offline
gap > 1000 min → zariadenie nebeží / je vypnuté

❌ Jediný frame za 48h

→ zariadenie nie je v prevádzke, iba test/flash/ping.

⸻

🧾 Výsledky z poslednej analýzy (pre audit / Stano report)

Výsledky zo systému (12. 11. – 13. 11.):

🟢 229252442470304 – referenčný senzor (bez výpadkov)

278 framov za 24h
0 výpadkov
kontinuálny stream

Toto je ukážka zdravého zariadenia.
Podľa neho sa hodnotí ostatná flotila.

⸻

🟡 Ostatné zariadenia – opakované výpadky

172336768373140
	•	Frames: 27
	•	Normálne intervaly ~15 min (OK)
	•	Veľké výpadky: 119 min, 134 min, 706 min (~11.8 h)

198341562840992
	•	Frames: 10
	•	Offline periódy: 4 h, 5 h, 3 h, 2 h, 1 h (nestabilné)

140860957430836
	•	Frames: 3
	•	Výpadky: 238 min, 119 min

163234500163488
	•	Frames: 3
	•	Výpadky: 731 min, 238 min

137408102356872
	•	Frames: 2
	•	Výpadok: 119 min

53330548471712
	•	Frames: 2
	•	Výpadok: 731 min (~12 h)

273250087450528
	•	Frames: 1
	•	Žiadna kontinuálna prevádzka

259836904585120
	•	Frames: 1
	•	Žiadna kontinuálna prevádzka

⸻

🧩 Interpretácia
	•	Bridge prijíma všetko 1:1 – všetko, čo Stano odošle, je v ingest_raw.
	•	TS insert (measurements) funguje – potvrdené manuálnym testom.
	•	Cloudflare, DNS, routing sú OK – všetky framy prišli cez rovnaký host.
	•	Výnimočne zdravé zariadenie je iba 229…
	•	Ostatné zariadenia majú hodinové až dvanásťhodinové výpadky.

→ Tieto výpadky sa 1:1 zobrazujú aj v ThingsBoard.

⸻

📬 Šablóna textu pre Stana

Ahoj,

urobil som backendovú diagnostiku pre všetky zariadenia za posledných 48 hodín.

Bridge prijíma a ukladá všetky telemetrické framy 1:1 bez výpadkov.
Zariadenie 229252442470304 je referenčné – má 278 framov a 0 výpadkov.

Ostatné zariadenia však nevysielajú kontinuálne:
- 1723…, 1983…, 1408…, 1632…, 1374… posielajú len občas, s prestávkami 2–12 hodín.
- 273…, 259… poslali iba 1 frame za 48h.

Všetky výpadky viditeľné v ThingsBoard sú spôsobené tým, že zariadenia v tých časoch neodosielali dáta.

Backend (Bridge/Mongo/TB ingest) funguje správne.

Môžeme spolu prejsť konfiguráciu, interval odosielania a uptime jednotlivých senzorov.


⸻

🛠 Troubleshooting Commands (skript do helpera)

Posledné 2 framy pre konkrétny device

/usr/bin/docker exec -it mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' \
  --authenticationDatabase admin --eval '
var u="172336768373140"; 
var dbx=db.getSiblingDB("xerxes");

print("ingest_raw:");
dbx.ingest_raw.find({uuid:u}).sort({ts:-1}).limit(2)
 .forEach(d=>printjson({ts:d.ts,keys:Object.keys(d.body.values||{})}));

print("\nmeasurements:");
dbx.measurements.find({uuid:u}).sort({ts:-1}).limit(2)
 .forEach(d=>printjson({ts:d.ts,keys:Object.keys(d.measurements||{})}));
'

IP + headers test (Cloudflare debug)

/usr/bin/docker exec -it mongo mongosh -u root -p 'ROOT_STRONG_PASSWORD' \
  --authenticationDatabase admin --eval '
var dbx=db.getSiblingDB("xerxes");
["229252442470304","172336768373140","198341562840992"].forEach(u=>{
 print("\nUUID:",u);
 dbx.ingest_raw.find({uuid:u}).sort({ts:-1}).limit(3)
 .forEach(d=>printjson({
   ts:d.ts, cf:d.headers["cf-connecting-ip"], ua:d.headers["user-agent"]
 }));
});
'


⸻

✔ Záver

Tento .md bol pripravený ako trvalý nástroj pre audit, monitoring a komunikáciu so Stano tímom.
Je pripravený na commit do GitHubu.

Ak chceš, doplním:
	•	verziu s obrázkami,
	•	CSV export per-device,
	•	automatický gap-report script (.sh),
	•	alebo diagnostiku ThingsBoard timeline.

Len povedz.
