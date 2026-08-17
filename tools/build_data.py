#!/usr/bin/env python3
"""Generate data.js from the canonical data/entries.csv, data/uv_entries.csv
and data/ram_entries.csv.

    python tools/build_data.py

Produces:
    window.SPEEDO_DATA = { "mariko": [...], "erista": [...] };   // speedo/RAM bin entries
    window.UV_FREQS    = { "mariko": [...], "erista": [...] };   // GPU freq steps (kHz)
    window.UV_DATA     = { "mariko": [...], "erista": [...] };   // GPU UV table submissions
    window.RAM_DATA    = { "mariko": [...], "erista": [...] };   // RAM timing/config submissions

Loaded via a plain <script> tag so it works on GitHub Pages and from file://.
Run this after any change to data/entries.csv, data/uv_entries.csv or
data/ram_entries.csv (the GitHub Action does this automatically for issue
submissions).
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "entries.csv"
UV_SRC = ROOT / "data" / "uv_entries.csv"
RAM_SRC = ROOT / "data" / "ram_entries.csv"
FREQS_SRC = ROOT / "data" / "gpu_freqs.json"
OUT = ROOT / "data.js"

# Numeric RAM fields, in the order they appear in ram_entries.csv (besides
# platform/owner/ram_type/notes, which aren't plain numbers). Kept in sync
# with tools/resolve_submissions.py's RAM_FIELDS and app.js's RAM_FIELD_GROUPS.
RAM_NUM_FIELDS = [
    "soc_speedo", "frequency", "vdd2", "vddq", "dvb_shift", "soc_max_volt",
    "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "tbreak",
    "low_t1", "low_t3", "low_t4", "low_t5", "low_t6", "low_t7", "low_t8",
    "read_latency_1333", "read_latency_1600", "read_latency_1866", "read_latency_2133",
    "write_latency_1333", "write_latency_1600", "write_latency_1866", "write_latency_2133",
]


def to_int(value):
    v = (value or "").strip()
    if not v:
        return None
    try:
        return round(float(v.replace(",", ".")))
    except ValueError:
        return None


# A per-frequency-step volt token is a blank (Auto, i.e. None), the literal
# "disabled" (that step is turned off — kept distinct from Auto), or an mV number.
def to_volt(value):
    v = (value or "").strip()
    if v.lower() == "disabled":
        return "disabled"
    return to_int(v)


def build_speedo_data():
    data = {"mariko": [], "erista": []}
    with SRC.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            platform = (row.get("platform") or "").strip().lower()
            if platform not in data:
                continue
            cpu, gpu, soc = to_int(row.get("cpu")), to_int(row.get("gpu")), to_int(row.get("soc"))
            if cpu is None and gpu is None and soc is None:
                continue
            model = (row.get("model") or "").strip()
            if not model:
                model = "V1" if platform == "erista" else "Unknown"
            data[platform].append({
                "owner": (row.get("owner") or "").strip() or "Anonymous",
                "model": model,
                "cpu": cpu, "gpu": gpu, "soc": soc,
                "ram": (row.get("ram") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
            })
    return data


def build_uv_data(freqs):
    data = {"mariko": [], "erista": []}
    if not UV_SRC.exists():
        return data
    with UV_SRC.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            platform = (row.get("platform") or "").strip().lower()
            if platform not in data:
                continue
            n = len(freqs[platform])
            tokens = (row.get("volts") or "").split(";")
            volts = [to_volt(t) for t in tokens[:n]]
            volts += [None] * (n - len(volts))
            if all(v is None for v in volts):
                continue
            data[platform].append({
                "owner": (row.get("owner") or "").strip() or "Anonymous",
                "gpu_speedo": to_int(row.get("gpu_speedo")),
                "uv_table": (row.get("uv_table") or "").strip() or "None",
                "voltage_offset": to_int(row.get("voltage_offset")) or 0,
                "vmin": to_int(row.get("vmin")),
                "notes": (row.get("notes") or "").strip(),
                "volts": volts,
            })
    return data


def build_ram_data():
    data = {"mariko": [], "erista": []}
    if not RAM_SRC.exists():
        return data
    with RAM_SRC.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            platform = (row.get("platform") or "").strip().lower()
            if platform not in data:
                continue
            entry = {
                "owner": (row.get("owner") or "").strip() or "Anonymous",
                "ram_type": (row.get("ram_type") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
            }
            for f in RAM_NUM_FIELDS:
                entry[f] = to_int(row.get(f))
            if entry["frequency"] is None and entry["soc_speedo"] is None:
                continue
            data[platform].append(entry)
    return data


def main():
    freqs = json.loads(FREQS_SRC.read_text(encoding="utf-8"))
    speedo_data = build_speedo_data()
    uv_data = build_uv_data(freqs)
    ram_data = build_ram_data()

    banner = (
        "// Auto-generated by tools/build_data.py from data/entries.csv,\n"
        "// data/uv_entries.csv and data/ram_entries.csv — do not edit by hand.\n"
        f"// mariko: {len(speedo_data['mariko'])} rows · erista: {len(speedo_data['erista'])} rows\n"
        f"// GPU UV submissions — mariko: {len(uv_data['mariko'])} · erista: {len(uv_data['erista'])}\n"
        f"// RAM submissions — mariko: {len(ram_data['mariko'])} · erista: {len(ram_data['erista'])}\n"
    )
    body = (
        "window.SPEEDO_DATA = " + json.dumps(speedo_data, ensure_ascii=False, indent=2) + ";\n"
        "window.UV_FREQS = " + json.dumps(freqs, ensure_ascii=False, indent=2) + ";\n"
        "window.UV_DATA = " + json.dumps(uv_data, ensure_ascii=False, indent=2) + ";\n"
        "window.RAM_DATA = " + json.dumps(ram_data, ensure_ascii=False, indent=2) + ";\n"
    )
    OUT.write_text(banner + body, encoding="utf-8")
    print(f"Wrote mariko={len(speedo_data['mariko'])} erista={len(speedo_data['erista'])} "
          f"speedo rows; uv mariko={len(uv_data['mariko'])} erista={len(uv_data['erista'])}; "
          f"ram mariko={len(ram_data['mariko'])} erista={len(ram_data['erista'])} to {OUT}")


if __name__ == "__main__":
    main()
