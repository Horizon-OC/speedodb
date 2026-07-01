#!/usr/bin/env python3
"""Resolve ALL open SpeedoDB submission issues in one pass.

Lists every open submission issue via the GitHub API, validates each, appends
the valid/unique ones to data/entries.csv, and writes results.json describing
what to do with each issue (comment + close, or comment error and leave open).

Doing the whole backlog in a single run — instead of one workflow run per issue
— means there is never a push race between concurrent runs, no matter how many
submissions arrive at once.

Env:
  GITHUB_TOKEN       token with repo + issues access (the workflow's GITHUB_TOKEN)
  GITHUB_REPOSITORY  "owner/repo"
Outputs:
  data/entries.csv   appended with new rows
  results.json       [{number, title, status: added|duplicate|error, message}]
"""
import csv
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "entries.csv"
RESULTS = ROOT / "results.json"
FIELDS = ["platform", "owner", "model", "cpu", "gpu", "soc", "ram", "notes"]

PLATFORM_MAP = {"mariko": "mariko", "erista": "erista"}
MARIKO_MODELS = {"OLED", "V2", "Lite"}
ERISTA_MODELS = {"V1 Unpatched", "V1 Patched"}
RANGES = {
    "mariko": {"cpu": (1425, 1825), "gpu": (1425, 1825), "soc": (1425, 1825)},
    "erista": {"cpu": (1825, 2200), "gpu": (1825, 2200), "soc": (1875, 2075)},
}

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
            if "### Platform" in body and "### Model" in body:
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


def validate(body):
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


def row_key(r):
    return (r["platform"], (r.get("owner") or "").strip().lower(), r.get("model") or "",
            r.get("cpu") or "", r.get("gpu") or "", r.get("soc") or "", (r.get("ram") or "").strip())


# ---------- main ----------

def main():
    existing = []
    if OUT.exists():
        with OUT.open("r", encoding="utf-8-sig", newline="") as fh:
            existing = list(csv.DictReader(fh))
    seen = {row_key(r) for r in existing}

    new_rows, results = [], []
    for it in list_open_submissions():
        num = it["number"]
        labels = [l["name"] for l in it.get("labels", [])]
        base = {"number": num, "title": it.get("title", ""), "labels": labels}
        row, err = validate(it.get("body") or "")
        if err:
            results.append({**base, "status": "error", "message": err})
        elif row_key(row) in seen:
            results.append({**base, "status": "duplicate", "message": ""})
        else:
            seen.add(row_key(row))
            new_rows.append(row)
            results.append({**base, "status": "added", "message": ""})

    if new_rows:
        new_file = not OUT.exists()
        with OUT.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerows(new_rows)

    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"Processed {len(results)} issues: {counts}; appended {len(new_rows)} rows.")


if __name__ == "__main__":
    main()
