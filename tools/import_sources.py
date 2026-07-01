#!/usr/bin/env python3
"""One-time importer: build the canonical data/entries.csv from the original
Mariko + Erista sheet exports.

    python tools/import_sources.py [mariko.csv] [erista.csv]

After this, data/entries.csv is the single source of truth. New submissions are
appended to it (by the GitHub Action), and tools/build_data.py turns it into
data.js. You normally only run this importer once.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "entries.csv"
FIELDS = ["platform", "owner", "model", "cpu", "gpu", "soc", "ram", "notes"]

DEFAULT_MARIKO = Path(
    r"C:\Users\sould\Downloads\Speedo documentation - Mariko_ Speedo, RAM & Models.csv"
)
DEFAULT_ERISTA = Path(
    r"C:\Users\sould\Downloads\Speedo documentation - Erista_ Speedo.csv"
)


def clean_int(value):
    if value is None:
        return ""
    v = value.strip().replace(" ", "")
    if not v or v == "?":
        return ""
    v = v.replace(",", ".")
    try:
        return str(round(float(v)))
    except ValueError:
        return ""


def main():
    mariko_src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MARIKO
    erista_src = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ERISTA
    rows = []

    with mariko_src.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for raw in reader:
            if not any(c.strip() for c in raw):
                continue
            owner = raw[0].strip()
            if owner.lower() == "averages":
                continue
            cpu, gpu, soc = (clean_int(raw[i]) if len(raw) > i else "" for i in (2, 3, 4))
            if not (cpu or gpu or soc):
                continue
            rows.append({
                "platform": "mariko", "owner": owner,
                "model": (raw[1].strip() if len(raw) > 1 else "") or "Unknown",
                "cpu": cpu, "gpu": gpu, "soc": soc,
                "ram": (raw[5].strip() if len(raw) > 5 else ""),
                "notes": (raw[6].strip() if len(raw) > 6 else ""),
            })

    with erista_src.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for raw in reader:
            if not any(c.strip() for c in raw):
                continue
            cpu, gpu, soc = (clean_int(raw[i]) if len(raw) > i else "" for i in (1, 2, 3))
            if not (cpu or gpu or soc):
                continue
            ram = (raw[4].strip() if len(raw) > 4 else "")
            rows.append({
                "platform": "erista", "owner": raw[0].strip(),
                "model": "V1",  # Erista; patch status isn't in the source data
                "cpu": cpu, "gpu": gpu, "soc": soc,
                "ram": ram or "HB-MGCH",  # blank Erista RAM defaults to HB-MGCH
                "notes": (raw[5].strip() if len(raw) > 5 else ""),
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
