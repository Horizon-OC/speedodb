# SpeedoDB

A static, GitHub Pages–hosted database of Nintendo Switch **speedo / IDDQ / RAM bin**
data, with averages and distribution charts by platform and console type.

- **Mariko** — OLED · V2 · Lite
- **Erista** — V1 (Unpatched / Patched)

Live charts cover CPU, GPU and SOC speedo distributions plus RAM bin breakdown,
recomputed for the selected platform and console type. Part of the
[Horizon-OC](https://horizon-oc.github.io) project.

## How it works

The site is fully static — no server. The dataset lives in
[`data/entries.csv`](data/entries.csv) and is compiled into [`data.js`](data.js)
(`window.SPEEDO_DATA`), which the page loads via a plain `<script>` tag (works on
Pages and from `file://`).

```text
data/entries.csv  ──(tools/build_data.py)──▶  data.js  ──▶  index.html + app.js
```

### Adding entries (for everyone)

The **+ Add entry** button opens a pre-filled
[GitHub issue form](.github/ISSUE_TEMPLATE/add-console.yml). When the issue is
submitted, the [`add-entry`](.github/workflows/add-entry.yml) workflow:

1. parses and validates the submission (`tools/issue_to_csv.py`),
2. appends a row to `data/entries.csv`,
3. regenerates `data.js` (`tools/build_data.py`),
4. commits the change and closes the issue (or comments back if invalid).

After the commit, the Pages deploy publishes the new data automatically.

## Local development

Just open `index.html` in a browser. To regenerate data after editing the CSV:

```sh
python tools/build_data.py
```

To (re)import from the original sheet exports into the canonical CSV:

```sh
python tools/import_sources.py "Mariko export.csv" "Erista export.csv"
```

## Deploying

Settings → **Pages** → **Source: GitHub Actions**. The
[`deploy-pages`](.github/workflows/deploy-pages.yml) workflow then publishes the
site on every push to `main`, and **redeploys automatically after each accepted
submission** (triggered via `workflow_run` once the submission workflow commits,
since the bot's `GITHUB_TOKEN` push doesn't fire `push` workflows itself). The
`.nojekyll` file keeps Pages from running Jekyll. The repo for issue links is
auto-detected from the Pages URL; override `REPO_FALLBACK` in `app.js` if needed.

## Notes

- Mariko and Erista speedos are on different scales, so they're kept as separate
  platforms rather than blended into one total.
- Erista patch status isn't present in the original data, so imported Erista
  units are recorded as plain `V1`; Unpatched/Patched fill in via submissions.
