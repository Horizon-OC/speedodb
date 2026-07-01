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

The **+ Add entry** button opens a pre-filled submission issue (matching the
[issue form](.github/ISSUE_TEMPLATE/add-console.yml)). The
[`resolve-submissions`](.github/workflows/resolve-submissions.yml) workflow then,
on any issue event (plus a 3-hourly safety sweep and manual dispatch),
processes **every open submission in a single run**:

1. lists all open submission issues via the API (`tools/resolve_submissions.py`),
2. validates each and appends the valid, unique ones to `data/entries.csv`,
3. regenerates `data.js` (`tools/build_data.py`) and pushes once,
4. labels, comments on, and closes each issue (leaving invalid ones open with an
   explanation).

Handling the whole backlog per run — rather than one run per issue — means many
submissions arriving at once never race to push. The workflow also applies the
`speedo-submission` label itself, since submitters usually can't set labels.
After the push, the Pages deploy publishes the new data automatically.

To clear a backlog immediately, run the workflow manually: Actions →
**Resolve submissions** → *Run workflow*.

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
