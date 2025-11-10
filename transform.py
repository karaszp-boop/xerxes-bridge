import time

def csq_to_rssi(csq: int | None):
    if csq is None or csq < 0 or csq > 31:
        return None
    return -113 + 2*csq

def to_tb_payload(doc: dict) -> dict:
    m = (doc.get("measurements") or {})
    meta = (doc.get("meta") or {})
    ts_raw = (((doc.get("time") or {}).get("server") or {}).get("epoch"))
    ts = int(round((ts_raw if ts_raw else time.time()) * 1000))
    csq = (((meta.get("modem") or {}).get("signalQuality")))
    values = {
        "temperature_c": m.get("temp"),
        "humidity_pct": m.get("rh"),
        "pm1_ugm3": m.get("pm1_0"),
        "pm25_ugm3": m.get("pm2_5"),
        "pm4_ugm3": m.get("pm4_0"),
        "pm10_ugm3": m.get("pm10"),
        "sound_dba": m.get("sound_db"),
        "voc_index": m.get("voc"),
        "nox_index": m.get("nox"),
        "battery_v": (((meta.get("power") or {}).get("battery") or {}).get("V")),
        "csq": csq,
        "rssi_dbm": csq_to_rssi(csq),
        "light_low_gain": m.get("light_low_gain"),
        "light_high_gain": m.get("light_high_gain")
    }
    values = {k: v for k, v in values.items() if v is not None}
    return {"ts": ts, "values": values}

def to_tb_attributes(doc: dict) -> dict:
    meta = (doc.get("meta") or {})
    attrs = {
        "uuid": str(doc.get("uuid") or meta.get("uuid") or ""),
        "fw_version": meta.get("version"),
        "boot_count": meta.get("bootCount"),
    }
    return {k: v for k, v in attrs.items() if v is not None}
