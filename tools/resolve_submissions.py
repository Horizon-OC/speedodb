#!/usr/bin/env python3
"""Resolve ALL open SpeedoDB submission issues in one pass.

Lists every open submission issue via the GitHub API (speedo/RAM-bin
submissions, GPU UV table submissions, and RAM timing/config submissions),
validates each, appends the valid/unique ones to the matching CSV, and writes
results.json describing what to do with each issue (comment + close, or
comment error and leave open).

Doing the whole backlog in a single run — instead of one workflow run per issue
— means there is never a push race between concurrent runs, no matter how many
submissions arrive at once.

Env:
  GITHUB_TOKEN       token with repo + issues access (the workflow's GITHUB_TOKEN)
  GITHUB_REPOSITORY  "owner/repo"
Outputs:
  data/entries.csv     appended with new speedo/RAM-bin rows
  data/uv_entries.csv  appended with new GPU UV table rows
  data/ram_entries.csv appended with new RAM timing/config rows
  results.json         [{number, title, status: added|duplicate|error, message, label}]
"""
import csv
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "entries.csv"
UV_OUT = ROOT / "data" / "uv_entries.csv"
RAM_OUT = ROOT / "data" / "ram_entries.csv"
FREQS_SRC = ROOT / "data" / "gpu_freqs.json"
RESULTS = ROOT / "results.json"
FIELDS = ["platform", "owner", "model", "cpu", "gpu", "soc", "ram", "notes"]
UV_FIELDS = ["platform", "owner", "gpu_speedo", "uv_table", "voltage_offset", "vmin", "notes", "volts"]
RAM_FIELDS = [
    "platform", "owner", "soc_speedo", "ram_type", "frequency", "vdd2", "vddq", "dvb_shift",
    "soc_max_volt", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "tbreak",
    "low_t1", "low_t3", "low_t4", "low_t5", "low_t6", "low_t7", "low_t8",
    "read_latency_1333", "read_latency_1600", "read_latency_1866", "read_latency_2133",
    "write_latency_1333", "write_latency_1600", "write_latency_1866", "write_latency_2133",
    "notes",
]

PLATFORM_MAP = {"mariko": "mariko", "erista": "erista"}
MARIKO_MODELS = {"OLED", "V2", "Lite"}
ERISTA_MODELS = {"V1 Unpatched", "V1 Patched"}
RANGES = {
    "mariko": {"cpu": (1425, 1825), "gpu": (1425, 1825), "soc": (1425, 1825)},
    "erista": {"cpu": (1825, 2200), "gpu": (1825, 2200), "soc": (1825, 2075)},
}
# Named UV table presets. Kept in sync with app.js's PLATFORMS[*].uvTables.
UV_TABLES = {
    "mariko": ["None", "SLT", "HiOPT", "HiOPT - 15", "High UV"],
    "erista": ["None", "HiOPT", "HiOPT - 15", "High UV"],
}
# Sane bounds for a per-frequency-step GPU voltage entry (mV), and for the
# single flat "voltage offset" applied on top of the whole curve.
UV_VOLT_RANGE = (300, 1300)
UV_OFFSET_RANGE = (-200, 200)
# GPU Vmin bounds, matching the hoc-clk overlay's own per-platform sliders.
UV_VMIN_RANGE = {"mariko": (400, 795), "erista": (650, 875)}
# Per-frequency-step tokens meaning "not set" (Auto, driver default) vs.
# "explicitly turned off" (Disabled) — kept distinct rather than collapsed
# into one blank/Auto state.
AUTO_TOKENS = {"0", "-", "x", "X", "auto", "Auto"}
DISABLED_TOKENS = {"disabled", "Disabled", "off", "Off"}
FREQS = json.loads(FREQS_SRC.read_text(encoding="utf-8"))

# RAM fields: (issue-body label, csv key, Mariko-only?, is 0 a valid
# "disabled" sentinel?, {platform: (lo, hi)}). Ranges are from the hoc-clk
# overlay's misc_gui.cpp (RamSubmenuGui / RamTimingsSubmenuGui /
# RamLatenciesSubmenuGui), except VDD2/VDDQ, whose source ranges come from an
# unlocked debug build and are capped here to the safer values actually used
# on release builds. Kept in sync with app.js's RAM_FIELD_GROUPS.
RAM_FIELD_DEFS = [
    ("Ram Max Clock", "frequency", False, False, {"mariko": (1600, 3400), "erista": (1600, 2400)}),
    ("VDD2", "vdd2", False, False, {"mariko": (913, 1350), "erista": (913, 1350)}),
    ("VDDQ", "vddq", True, False, {"mariko": (400, 750)}),
    ("DVB Shift", "dvb_shift", False, False, {"mariko": (-4, 8), "erista": (-4, 8)}),
    ("t1 tRCD", "t1", False, False, {"mariko": (0, 7), "erista": (0, 7)}),
    ("t2 tRP", "t2", False, False, {"mariko": (0, 7), "erista": (0, 7)}),
    ("t3 tRAS", "t3", False, False, {"mariko": (0, 9), "erista": (0, 9)}),
    ("t4 tRRD", "t4", False, False, {"mariko": (0, 6), "erista": (0, 6)}),
    ("t5 tRFC", "t5", False, False, {"mariko": (0, 10), "erista": (0, 5)}),
    ("t6 tRTW", "t6", False, False, {"mariko": (0, 9), "erista": (0, 9)}),
    ("t7 tWTR", "t7", False, False, {"mariko": (0, 9), "erista": (0, 9)}),
    ("t8 tREFI", "t8", False, False, {"mariko": (0, 6), "erista": (0, 6)}),
    ("tBreak", "tbreak", True, True, {"mariko": (1600, 3400)}),
    ("Low t1 tRCD", "low_t1", True, False, {"mariko": (0, 7)}),
    ("Low t3 tRAS", "low_t3", True, False, {"mariko": (0, 9)}),
    ("Low t4 tRRD", "low_t4", True, False, {"mariko": (0, 6)}),
    ("Low t5 tRFC", "low_t5", True, False, {"mariko": (0, 10)}),
    ("Low t6 tRTW", "low_t6", True, False, {"mariko": (0, 9)}),
    ("Low t7 tWTR", "low_t7", True, False, {"mariko": (0, 9)}),
    ("Low t8 tREFI", "low_t8", True, False, {"mariko": (0, 6)}),
    ("Read Latency 1333", "read_latency_1333", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Read Latency 1600", "read_latency_1600", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Read Latency 1866", "read_latency_1866", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Read Latency 2133", "read_latency_2133", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Write Latency 1333", "write_latency_1333", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Write Latency 1600", "write_latency_1600", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Write Latency 1866", "write_latency_1866", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
    ("Write Latency 2133", "write_latency_2133", False, True, {"mariko": (1600, 3300), "erista": (1600, 2400)}),
]
RAM_SOC_MAX_VOLT_OPTIONS = {0, 1000, 1025, 1050, 1075, 1100, 1125, 1150, 1175, 1200, 1225, 1250, 1275, 1300}

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")


# ---------- GitHub API ----------

def api_get(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "speedodb-bot"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def issue_kind(body):
    """Classify an issue body as a speedo, UV or RAM submission, or neither."""
    if "### Platform" not in body:
        return None
    if "### Model" in body:
        return "speedo"
    if "### Voltage table" in body:
        return "uv"
    if "### RAM Type" in body:
        return "ram"
    return None


def list_open_submissions():
    issues, page = [], 1
    while True:
        batch = api_get(f"/repos/{REPO}/issues?state=open&per_page=100&page={page}")
        if not batch:
            break
        for it in batch:
            if "pull_request" in it:
                continue
            body = it.get("body") or ""
            if issue_kind(body):
                issues.append(it)
        page += 1
    # Oldest first, so the dataset order is stable and reproducible.
    issues.sort(key=lambda it: it["number"])
    return issues


# ---------- parsing / validation ----------

def parse_issue(body):
    sections, cur, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^###\s+(.*)", line.strip())
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    return sections


def clean_int(value):
    digits = re.sub(r"[^\d]", "", value or "")
    return digits if digits else ""


def clean_signed_int(value):
    v = (value or "").strip()
    return v if re.fullmatch(r"-?\d+", v) else ""


def validate_speedo(body):
    """Return (row, None) if valid, else (None, error_message)."""
    s = parse_issue(body)

    def get(label):
        v = (s.get(label) or "").strip()
        return "" if v in ("", "_No response_") else v

    platform = PLATFORM_MAP.get(get("Platform").lower())
    if not platform:
        return None, "Platform must be Mariko or Erista."

    model = get("Model")
    valid = MARIKO_MODELS if platform == "mariko" else ERISTA_MODELS
    if model not in valid:
        return None, (f"Model '{model}' is not valid for {platform.title()} "
                      f"(expected one of: {', '.join(sorted(valid))}).")

    cpu, gpu, soc = clean_int(get("CPU speedo")), clean_int(get("GPU speedo")), clean_int(get("SOC speedo"))
    if not (cpu or gpu or soc):
        return None, "At least one of CPU / GPU / SOC speedo must be a number."

    for field, val in (("cpu", cpu), ("gpu", gpu), ("soc", soc)):
        if val:
            lo, hi = RANGES[platform][field]
            if not (lo <= int(val) <= hi):
                return None, (f"{field.upper()} speedo {val} is outside the valid "
                              f"{platform.title()} range ({lo}–{hi}).")

    ram = get("RAM bin")
    if platform == "erista" and not ram:
        ram = "HB-MGCH"

    return {
        "platform": platform,
        "owner": (get("Owner / handle") or "Anonymous")[:40],
        "model": model,
        "cpu": cpu, "gpu": gpu, "soc": soc,
        "ram": ram[:20],
        "notes": get("Notes").replace("\n", " ")[:240],
    }, None


def validate_uv(body):
    """Return (row, None) if valid, else (None, error_message)."""
    s = parse_issue(body)

    def get(label):
        v = (s.get(label) or "").strip()
        return "" if v in ("", "_No response_") else v

    platform = PLATFORM_MAP.get(get("Platform").lower())
    if not platform:
        return None, "Platform must be Mariko or Erista."

    gpu = clean_int(get("GPU speedo"))
    if not gpu:
        return None, "GPU speedo is required for a UV table submission."
    lo, hi = RANGES[platform]["gpu"]
    if not (lo <= int(gpu) <= hi):
        return None, (f"GPU speedo {gpu} is outside the valid "
                      f"{platform.title()} range ({lo}–{hi}).")

    uv_table = get("UV table") or "None"
    if uv_table not in UV_TABLES[platform]:
        return None, (f"UV table '{uv_table}' is not valid for {platform.title()} "
                      f"(expected one of: {', '.join(UV_TABLES[platform])}).")

    offset_raw = get("Voltage offset") or "0"
    if not re.fullmatch(r"-?\d+", offset_raw):
        return None, f"Voltage offset '{offset_raw}' is not a whole number."
    offset = int(offset_raw)
    lo_o, hi_o = UV_OFFSET_RANGE
    if not (lo_o <= offset <= hi_o):
        return None, f"Voltage offset {offset} is outside the sane range ({lo_o}–{hi_o} mV)."

    vmin = clean_int(get("Vmin"))
    if not vmin:
        return None, "Vmin is required for a UV table submission."
    lo_m, hi_m = UV_VMIN_RANGE[platform]
    if not (lo_m <= int(vmin) <= hi_m):
        return None, (f"Vmin {vmin} is outside the valid {platform.title()} "
                      f"range ({lo_m}–{hi_m}).")

    freqs = FREQS[platform]
    raw = get("Voltage table")
    if not raw:
        return None, "Voltage table is required."
    # Accept one value per line and/or comma-separated. "0"/"-"/"x"/"auto"
    # mean Auto (driver default); "disabled"/"off" mean that step is turned
    # off entirely — the two are kept distinct, not collapsed into one blank.
    tokens = [t.strip() for t in re.split(r"[,\n]+", raw) if t.strip() != ""]
    if len(tokens) != len(freqs):
        return None, (f"Voltage table must have exactly {len(freqs)} values for "
                      f"{platform.title()} (one per frequency step, in order) — got {len(tokens)}.")

    volts = []
    for i, tok in enumerate(tokens):
        if tok in AUTO_TOKENS:
            volts.append(None)
            continue
        if tok in DISABLED_TOKENS:
            volts.append("disabled")
            continue
        if not re.fullmatch(r"\d+", tok):
            return None, f"Voltage table entry #{i + 1} ('{tok}') is not a number."
        v = int(tok)
        lo_v, hi_v = UV_VOLT_RANGE
        if not (lo_v <= v <= hi_v):
            return None, (f"Voltage table entry #{i + 1} ({v} mV, for {freqs[i]} kHz) is outside "
                          f"the sane range ({lo_v}–{hi_v} mV).")
        volts.append(v)

    if all(v is None for v in volts):
        return None, "Voltage table can't be all Auto/blank — enter at least one value."

    return {
        "platform": platform,
        "owner": (get("Owner / handle") or "Anonymous")[:40],
        "gpu_speedo": gpu,
        "uv_table": uv_table,
        "voltage_offset": offset,
        "vmin": vmin,
        "notes": get("Notes").replace("\n", " ")[:240],
        "volts": ";".join("" if v is None else str(v) for v in volts),
    }, None


def validate_ram(body):
    """Return (row, None) if valid, else (None, error_message)."""
    s = parse_issue(body)

    def get(label):
        v = (s.get(label) or "").strip()
        return "" if v in ("", "_No response_") else v

    platform = PLATFORM_MAP.get(get("Platform").lower())
    if not platform:
        return None, "Platform must be Mariko or Erista."

    ram_type = get("RAM Type")
    if not ram_type:
        return None, "RAM Type is required."

    soc = clean_int(get("SOC Speedo"))
    if not soc:
        return None, "SOC Speedo is required for a RAM submission."
    lo, hi = RANGES[platform]["soc"]
    if not (lo <= int(soc) <= hi):
        return None, (f"SOC Speedo {soc} is outside the valid "
                      f"{platform.title()} range ({lo}–{hi}).")

    row = {
        "platform": platform,
        "owner": (get("Owner / handle") or "Anonymous")[:40],
        "ram_type": ram_type[:20],
        "soc_speedo": soc,
    }

    for label, key, mariko_only, zero_ok, ranges_by_platform in RAM_FIELD_DEFS:
        if mariko_only and platform != "mariko":
            row[key] = ""
            continue
        raw = get(label)
        parser = clean_signed_int if key == "dvb_shift" else clean_int
        cleaned = parser(raw)
        if not cleaned:
            if key == "frequency":
                return None, "Ram Max Clock is required for a RAM submission."
            row[key] = ""
            continue
        val = int(cleaned)
        if zero_ok and val == 0:
            row[key] = "0"
            continue
        lo_f, hi_f = ranges_by_platform[platform]
        if not (lo_f <= val <= hi_f):
            return None, (f"{label} {val} is outside the valid {platform.title()} "
                          f"range ({lo_f}–{hi_f}).")
        row[key] = str(val)

    if platform == "mariko":
        smv_raw = get("SoC Max Volt")
        cleaned = clean_int(smv_raw)
        if cleaned:
            smv = int(cleaned)
            if smv not in RAM_SOC_MAX_VOLT_OPTIONS:
                return None, (f"SoC Max Volt {smv} is not one of the valid options "
                              f"({', '.join(str(v) for v in sorted(RAM_SOC_MAX_VOLT_OPTIONS))}).")
            row["soc_max_volt"] = str(smv)
        else:
            row["soc_max_volt"] = ""
    else:
        row["soc_max_volt"] = ""

    row["notes"] = get("Notes").replace("\n", " ")[:240]
    return row, None


def row_key(r):
    return (r["platform"], (r.get("owner") or "").strip().lower(), r.get("model") or "",
            r.get("cpu") or "", r.get("gpu") or "", r.get("soc") or "", (r.get("ram") or "").strip())


def uv_row_key(r):
    return (r["platform"], (r.get("owner") or "").strip().lower(), r.get("gpu_speedo") or "",
            r.get("uv_table") or "", r.get("voltage_offset") or "", r.get("vmin") or "", r.get("volts") or "")


def ram_row_key(r):
    return tuple((r.get(f) or "").strip().lower() if f in ("platform", "owner", "ram_type") else (r.get(f) or "")
                 for f in RAM_FIELDS if f != "notes")


# ---------- main ----------

def load_existing(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def append_rows(path, fields, rows):
    if not rows:
        return
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new_file:
            w.writeheader()
        w.writerows(rows)


KINDS = {
    "speedo": {"validate": validate_speedo, "key": row_key, "out": OUT, "fields": FIELDS, "label": "speedo-submission"},
    "uv": {"validate": validate_uv, "key": uv_row_key, "out": UV_OUT, "fields": UV_FIELDS, "label": "uv-submission"},
    "ram": {"validate": validate_ram, "key": ram_row_key, "out": RAM_OUT, "fields": RAM_FIELDS, "label": "ram-submission"},
}


def main():
    seen = {k: {v["key"](r) for r in load_existing(v["out"])} for k, v in KINDS.items()}
    new_rows = {k: [] for k in KINDS}
    results = []

    for it in list_open_submissions():
        num = it["number"]
        labels = [l["name"] for l in it.get("labels", [])]
        kind = issue_kind(it.get("body") or "")
        cfg = KINDS[kind]
        base = {"number": num, "title": it.get("title", ""), "labels": labels, "kind": kind, "label": cfg["label"]}

        row, err = cfg["validate"](it.get("body") or "")
        if err:
            results.append({**base, "status": "error", "message": err})
        elif cfg["key"](row) in seen[kind]:
            results.append({**base, "status": "duplicate", "message": ""})
        else:
            seen[kind].add(cfg["key"](row))
            new_rows[kind].append(row)
            results.append({**base, "status": "added", "message": ""})

    for k, cfg in KINDS.items():
        append_rows(cfg["out"], cfg["fields"], new_rows[k])

    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    added = {k: len(v) for k, v in new_rows.items()}
    print(f"Processed {len(results)} issues: {counts}; appended {added}.")


if __name__ == "__main__":
    main()
