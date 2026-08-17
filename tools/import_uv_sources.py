#!/usr/bin/env python3
"""One-time importer: build data/uv_entries.csv from the original Mariko +
Erista GPU UV sheet exports.

    python tools/import_uv_sources.py [mariko_uv.csv] [erista_uv.csv]

Each source sheet has one column per frequency step (labelled in MHz, e.g.
"768MHz"), matching the per-platform step list in data/gpu_freqs.json exactly
— that list only includes steps the sheets actually test, plus Erista's
1075MHz headroom step, which no sheet row has data for and so is always left
unset (Auto). Every header column is matched to a step 1:1; nothing is
extrapolated.

The Erista sheet's SOC speedo and Ram columns aren't part of the UV table
schema and are intentionally ignored. vMin *is* captured from both sheets.
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "uv_entries.csv"
FREQS = json.loads((ROOT / "data" / "gpu_freqs.json").read_text(encoding="utf-8"))
FIELDS = ["platform", "owner", "gpu_speedo", "uv_table", "voltage_offset", "vmin", "notes", "volts"]

# Neither source sheet records a UV table preset or a flat voltage offset —
# every row here is a submitter's own hand-tuned per-frequency table (what
# "High UV" denotes) with no additional offset applied on top.
DEFAULT_UV_TABLE = "High UV"
DEFAULT_VOLTAGE_OFFSET = 0

DEFAULT_MARIKO = Path(r"C:\Users\sould\Downloads\Speedo documentation - Mariko_GPU_UV.csv")
DEFAULT_ERISTA = Path(r"C:\Users\sould\Downloads\Speedo documentation - Erista_GPU_UV.csv")


def mv(cell):
    m = re.search(r"\d+", cell or "")
    return int(m.group()) if m else None


def freq_columns(header, platform):
    """Map each "NNNMHz" header column to its index in the canonical
    per-platform frequency list (kHz)."""
    freqs = FREQS[platform]
    # Header labels are the kHz value truncated (not rounded) to MHz, e.g.
    # 844800 kHz -> "844MHz", 1305600 kHz -> "1305MHz".
    khz_by_mhz = {f // 1000: i for i, f in enumerate(freqs)}
    mapping = {}
    for col, name in enumerate(header):
        m = re.fullmatch(r"\s*(\d+)\s*MHz\s*", name or "")
        if not m:
            continue
        mhz = int(m.group(1))
        if mhz not in khz_by_mhz:
            raise ValueError(f"Header column '{name}' ({mhz} MHz) doesn't match any "
                              f"{platform} frequency step in gpu_freqs.json.")
        mapping[col] = khz_by_mhz[mhz]
    return mapping


def import_sheet(path, platform):
    freqs = FREQS[platform]
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        col_to_idx = freq_columns(header, platform)
        try:
            gpu_col = header.index("GPU speedo")
        except ValueError:
            gpu_col = header.index("GPU Speedo")
        owner_col = header.index("Username")
        note_col = header.index("Note")
        vmin_col = header.index("vMin")

        for raw in reader:
            if not any(c.strip() for c in raw):
                continue
            gpu = mv(raw[gpu_col]) if len(raw) > gpu_col else None
            owner = raw[owner_col].strip() if len(raw) > owner_col else ""
            if not gpu or not owner:
                continue
            notes = (raw[note_col].strip() if len(raw) > note_col else "").replace("\n", " ")
            vmin = mv(raw[vmin_col]) if len(raw) > vmin_col else None

            volts = [None] * len(freqs)
            for col, idx in col_to_idx.items():
                if col < len(raw):
                    volts[idx] = mv(raw[col])

            rows.append({
                "platform": platform,
                "owner": owner,
                "gpu_speedo": gpu,
                "uv_table": DEFAULT_UV_TABLE,
                "voltage_offset": DEFAULT_VOLTAGE_OFFSET,
                "vmin": vmin if vmin is not None else "",
                "notes": notes,
                "volts": ";".join("" if v is None else str(v) for v in volts),
            })
    return rows


def main():
    mariko_src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MARIKO
    erista_src = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ERISTA

    rows = import_sheet(mariko_src, "mariko") + import_sheet(erista_src, "erista")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
