#!/usr/bin/env python3
"""Append a row to data/entries.csv from a SpeedoDB submission issue.

Reads the GitHub issue-form body from the ISSUE_BODY env var (set by the
workflow). Validates it and appends one row. Exits non-zero with a message on
GITHUB_OUTPUT (key `error`) if the submission is invalid, so the workflow can
comment back on the issue.
"""
import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "entries.csv"
FIELDS = ["platform", "owner", "model", "cpu", "gpu", "soc", "ram", "notes"]

PLATFORM_MAP = {"mariko": "mariko", "erista": "erista"}
MARIKO_MODELS = {"OLED", "V2", "Lite"}
ERISTA_MODELS = {"V1", "V1 Unpatched", "V1 Patched"}

# Plausible speedo ranges per platform and field (inclusive).
RANGES = {
    "mariko": {"cpu": (1425, 1825), "gpu": (1425, 1825), "soc": (1425, 1825)},
    "erista": {"cpu": (1825, 2200), "gpu": (1825, 2200), "soc": (1875, 2075)},
}


def parse_issue(body):
    """Issue forms render as '### Label\\n\\nvalue' blocks."""
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


def set_output(key, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def fail(msg):
    set_output("error", msg)
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def clean_int(value):
    digits = re.sub(r"[^\d]", "", value or "")
    return digits if digits else ""


def main():
    body = os.environ.get("ISSUE_BODY", "")
    s = parse_issue(body)

    def get(label):
        v = (s.get(label) or "").strip()
        return "" if v in ("", "_No response_") else v

    platform = PLATFORM_MAP.get(get("Platform").lower())
    if not platform:
        fail("Platform must be Mariko or Erista.")

    model = get("Model")
    valid = MARIKO_MODELS if platform == "mariko" else ERISTA_MODELS
    if model not in valid:
        fail(f"Model '{model}' is not valid for {platform.title()} "
             f"(expected one of: {', '.join(sorted(valid))}).")

    cpu, gpu, soc = clean_int(get("CPU speedo")), clean_int(get("GPU speedo")), clean_int(get("SOC speedo"))
    if not (cpu or gpu or soc):
        fail("At least one of CPU / GPU / SOC speedo must be a number.")

    for field, val in (("cpu", cpu), ("gpu", gpu), ("soc", soc)):
        if val:
            lo, hi = RANGES[platform][field]
            if not (lo <= int(val) <= hi):
                fail(f"{field.upper()} speedo {val} is outside the valid "
                     f"{platform.title()} range ({lo}–{hi}).")

    ram = get("RAM bin")
    if platform == "erista" and not ram:
        ram = "MGCH"

    row = {
        "platform": platform,
        "owner": (get("Owner / handle") or "Anonymous")[:40],
        "model": model,
        "cpu": cpu, "gpu": gpu, "soc": soc,
        "ram": ram[:20],
        "notes": get("Notes").replace("\n", " ")[:240],
    }

    # Reject exact duplicates already in the dataset (same owner/model/speedos/ram).
    def key(r):
        return (
            r["platform"], (r.get("owner") or "").strip().lower(), r.get("model") or "",
            r.get("cpu") or "", r.get("gpu") or "", r.get("soc") or "", (r.get("ram") or "").strip(),
        )
    # A duplicate is treated as a graceful no-op (not an error): the data is
    # already present, so we just report it. This also makes the workflow safe
    # against the same issue triggering twice (e.g. `opened` + `labeled`) — the
    # second run finds the first run's row and quietly succeeds instead of
    # posting a spurious failure.
    if OUT.exists():
        with OUT.open("r", encoding="utf-8-sig", newline="") as fh:
            existing = {key(r) for r in csv.DictReader(fh)}
        if key(row) in existing:
            set_output("status", "duplicate")
            print(f"Duplicate, skipping: {row}")
            return

    new_file = not OUT.exists()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)

    set_output("status", "added")
    print(f"Appended: {row}")


if __name__ == "__main__":
    main()
