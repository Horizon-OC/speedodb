/* SpeedoDB — client-side app. Speedo/RAM data comes from window.SPEEDO_DATA and
   GPU UV table data from window.UV_DATA/window.UV_FREQS (all in data.js,
   generated from data/entries.csv and data/uv_entries.csv). New entries are
   submitted as GitHub issues ("Add entry" / "Add UV table"), which a workflow
   validates and commits to the dataset. */
(function () {
  "use strict";

  const PLATFORMS = {
    // sort: default table sort key for the platform. Erista defaults to GPU
    // speedo, which is the more reliable metric on those units; Mariko uses SOC.
    // uvTables: named UV table presets, kept in sync with
    // tools/resolve_submissions.py's UV_TABLES.
    mariko: { label: "Mariko", order: ["OLED", "V2", "Lite"], sort: "soc",
      ram: ["AA-MGCL", "AB-MGCL", "AM-MGCJ", "NEE", "NME", "WT:B", "WT:E", "WT:F"],
      uvTables: ["None", "SLT", "HiOPT", "HiOPT - 15", "High UV"] },
    erista: { label: "Erista", order: ["V1 Unpatched", "V1 Patched"], sort: "gpu",
      ram: ["HB-MGCH", "NLE", "WT:C"],
      uvTables: ["None", "HiOPT", "HiOPT - 15", "High UV"] },
  };

  // Repo used for issue-submission links. Auto-detected on GitHub Pages, with
  // this constant as a fallback (edit if the repo ever moves).
  const REPO_FALLBACK = "Horizon-OC/speedoDB";

  const SPEEDOS = [
    { key: "cpu", label: "CPU speedo", canvas: "cpuChart", color: "#ffd166" },
    { key: "gpu", label: "GPU speedo", canvas: "gpuChart", color: "#06d6a0" },
    { key: "soc", label: "SOC speedo", canvas: "socChart", color: "#4cc9f0" },
  ];

  // Plausible speedo ranges per platform/field (inclusive). Kept in sync with
  // tools/resolve_submissions.py, which is the authoritative server-side check.
  const RANGES = {
    mariko: { cpu: [1425, 1825], gpu: [1425, 1825], soc: [1425, 1825] },
    erista: { cpu: [1825, 2200], gpu: [1825, 2200], soc: [1825, 2075] },
  };

  const state = {
    platform: "mariko",
    consoleType: "Total",
    search: "",
    sortKey: "soc",
    sortDir: -1, // -1 desc, 1 asc
    view: "speedo", // "speedo" | "uv"
  };

  // Sane bounds for a per-frequency-step GPU voltage entry (mV) and for the
  // flat voltage offset applied on top of the whole curve. Kept in sync with
  // tools/resolve_submissions.py, which is the authoritative check.
  const UV_VOLT_RANGE = [300, 1300];
  const UV_OFFSET_RANGE = [-200, 200];
  // GPU Vmin bounds, matching the hoc-clk overlay's own per-platform sliders.
  const UV_VMIN_RANGE = { mariko: [400, 795], erista: [650, 875] };

  // CVB (core-voltage-bias) coefficients — [baseUv, c1, c2, c3, c4, c5] per
  // row, same layout as nvgpu's gm20b cvb_coefficients — used to compute the
  // stock driver voltage for a step left on "Auto", for the curve graph.
  // One row per frequency step *covered by the real stock DVFS table*:
  // Mariko's 18 rows line up 1:1 with uvFreqs()[0..17] (76800-1305600kHz);
  // anything past that is OC-only headroom with no stock curve. Erista's
  // rows only line up 1:1 through row 11 (921600kHz) — beyond that, the
  // stock hardware table has steps (960000, 1036800...) that we deliberately
  // don't expose as selectable frequencies, so row order and our pruned
  // frequency list diverge and can't be used for Auto-fill.
  const GPU_CVB = {
    mariko: [
      [480000, 0, 0, 0, 0, 0],
      [480000, 0, 0, 0, 0, 0],
      [480000, 0, 0, 0, 0, 0],
      [738712, -7304, -552, 119, -3750, -2],
      [758712, -7304, -552, 119, -3750, -2],
      [778712, -7304, -552, 119, -3750, -2],
      [798712, -7304, -552, 119, -3750, -2],
      [818712, -7304, -552, 119, -3750, -2],
      [838712, -7304, -552, 119, -3750, -2],
      [880210, -7955, -584, 0, -2849, 39],
      [926398, -8892, -602, -60, -384, -93],
      [970060, -10108, -614, -179, 1508, -13],
      [1060665, -16075, -497, -179, 3213, 9],
      [1061475, -12688, -648, 0, 1077, 40],
      [1094475, -12688, -648, 0, 1077, 40],
      [1124475, -12688, -648, 0, 1077, 40],
      [1142060, -12688, -648, 0, 1077, 40],
      [1163644, -12688, -648, 0, 1077, 40],
    ],
    erista: [
      [480000, 0, 0, 0, 0, 0],
      [480000, 0, 0, 0, 0, 0],
      [480000, 0, 0, 0, 0, 0],
      [738712, -7304, -552, 119, -3750, -2],
      [758712, -7304, -552, 119, -3750, -2],
      [778712, -7304, -552, 119, -3750, -2],
      [798712, -7304, -552, 119, -3750, -2],
      [818712, -7304, -552, 119, -3750, -2],
      [838712, -7304, -552, 119, -3750, -2],
      [880210, -7955, -584, 0, -2849, 39],
      [926398, -8892, -602, -60, -384, -93],
      [970060, -10108, -614, -179, 1508, -13],
    ],
  };

  function floorDiv(a, b) { return Math.floor(a / b); }
  // Port of the reference calculator's div_round_closest: round-half-away-
  // from-zero integer division.
  function divRoundClosest(value, scale) {
    return value > 0 ? floorDiv(value + floorDiv(scale, 2), scale)
                      : floorDiv(value - floorDiv(scale, 2), scale);
  }
  function round5(n) { return Math.ceil(n / 5000) * 5000; }

  // Stock ("Auto") GPU voltage for one frequency step, at the worst-case
  // 90°C thermal bracket — the highest (most conservative) of the reference
  // script's 6 temperature floors, and the one most representative of real
  // sustained-load behavior. offsetMv is folded into the base coefficient
  // exactly as the reference script does (subtracted before the curve math).
  function cvbAutoVoltage(cvb, speedo, offsetMv, vminMv) {
    const base = cvb[0] - offsetMv * 1000;
    let mv = divRoundClosest(cvb[2] * speedo, 100);
    mv = divRoundClosest((mv + cvb[1]) * speedo, 100) + base;

    const t = 90;
    let mvt = divRoundClosest(cvb[3] * speedo, 100) + cvb[4] + divRoundClosest(cvb[5] * t, 10);
    mvt = divRoundClosest(mvt * t, 10);

    const finalMv = round5(mv + mvt) / 1000;
    return Math.max(finalMv, vminMv);
  }

  // null if this step has no stock curve coverage (OC-only headroom, or an
  // Erista step past the hardware/UI alignment break described above).
  function autoVoltageFor(platform, freqIndex, speedo, offsetMv, vminMv) {
    const cvb = GPU_CVB[platform];
    if (!cvb || freqIndex >= cvb.length || speedo == null || vminMv == null) return null;
    return cvbAutoVoltage(cvb[freqIndex], speedo, offsetMv, vminMv);
  }

  const charts = { cpu: null, gpu: null, soc: null, ram: null, uv: null };

  /* ---------- data helpers ---------- */

  function platformEntries() {
    return window.SPEEDO_DATA[state.platform] || [];
  }

  function uvFreqs() {
    return (window.UV_FREQS && window.UV_FREQS[state.platform]) || [];
  }

  function platformUvEntries() {
    return (window.UV_DATA && window.UV_DATA[state.platform]) || [];
  }

  // Canonical models are always shown (even with 0 entries, e.g. V1
  // Unpatched/Patched); any other models found in the data are appended.
  function consoleTypes(entries) {
    const ordered = PLATFORMS[state.platform].order.slice();
    const present = new Set(entries.map(e => e.model || "Unknown"));
    const extras = [...present].filter(m => !ordered.includes(m)).sort();
    return ordered.concat(extras);
  }

  function filterByType(entries) {
    if (state.consoleType === "Total") return entries;
    return entries.filter(e => (e.model || "Unknown") === state.consoleType);
  }

  function avg(nums) {
    const v = nums.filter(n => typeof n === "number" && !isNaN(n));
    if (!v.length) return null;
    return v.reduce((a, b) => a + b, 0) / v.length;
  }
  const fmt = n => (n === null ? "—" : Math.round(n).toLocaleString());

  // Deterministic color per RAM bin so pills and pie slices always match.
  function ramColor(label) {
    let h = 0;
    const s = label || "?";
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return `hsl(${h}, 62%, 55%)`;
  }

  function getRepo() {
    const m = location.hostname.match(/^([^.]+)\.github\.io$/i);
    if (m) {
      const parts = location.pathname.split("/").filter(Boolean);
      if (parts.length && parts[parts.length - 1].includes(".")) parts.pop();
      return parts.length ? `${m[1]}/${parts[0]}` : `${m[1]}/${m[1]}.github.io`;
    }
    return REPO_FALLBACK;
  }

  /* ---------- rendering ---------- */

  function renderPlatformButtons() {
    document.querySelectorAll(".platform-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.platform === state.platform);
    });
  }

  function renderTabs(entries) {
    const tabs = document.getElementById("tabs");
    const types = ["Total", ...consoleTypes(entries)];
    if (!types.includes(state.consoleType)) state.consoleType = "Total";
    tabs.innerHTML = "";
    types.forEach(type => {
      const n = type === "Total" ? entries.length
        : entries.filter(e => (e.model || "Unknown") === type).length;
      const b = document.createElement("button");
      b.className = "tab" + (type === state.consoleType ? " active" : "");
      b.innerHTML = `${type}<span class="count">${n}</span>`;
      b.onclick = () => { state.consoleType = type; render(); };
      tabs.appendChild(b);
    });
  }

  function renderStats(rows) {
    const el = document.getElementById("stats");
    el.innerHTML = "";
    SPEEDOS.forEach(d => {
      const vals = rows.map(r => r[d.key]).filter(n => typeof n === "number");
      const mean = avg(vals);
      const min = vals.length ? Math.min(...vals) : null;
      const max = vals.length ? Math.max(...vals) : null;
      const card = document.createElement("div");
      card.className = `stat ${d.key}`;
      card.innerHTML =
        `<div class="label">Avg ${d.label}</div>
         <div class="value">${fmt(mean)}</div>
         <div class="sub">min ${fmt(min)} · max ${fmt(max)} · ${vals.length} units</div>`;
      el.appendChild(card);
    });

    const count = document.createElement("div");
    count.className = "stat";
    count.innerHTML =
      `<div class="label">Consoles</div>
       <div class="value">${rows.length}</div>
       <div class="sub">${PLATFORMS[state.platform].label} · ${state.consoleType}</div>`;
    el.appendChild(count);
  }

  function renderRamChart(rows) {
    const counts = {};
    rows.forEach(r => {
      const k = (r.ram || "Unknown").trim() || "Unknown";
      counts[k] = (counts[k] || 0) + 1;
    });
    const labels = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    const data = labels.map(l => counts[l]);
    const total = data.reduce((a, b) => a + b, 0);

    if (charts.ram) charts.ram.destroy();
    charts.ram = new Chart(document.getElementById("ramChart"), {
      type: "doughnut",
      data: { labels, datasets: [{ data, backgroundColor: labels.map(ramColor),
        borderColor: "#161b22", borderWidth: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { color: "#e6edf3", boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: c =>
            `${c.label}: ${c.parsed} (${((c.parsed / total) * 100).toFixed(1)}%)` } }
        }
      }
    });
  }

  function renderSpeedoChart(def, rows) {
    const vals = rows.map(r => r[def.key]).filter(n => typeof n === "number");
    if (charts[def.key]) charts[def.key].destroy();
    if (!vals.length) { charts[def.key] = null; return; }

    const min = Math.min(...vals), max = Math.max(...vals);
    const step = 25;
    const start = Math.floor(min / step) * step;
    const end = Math.max(start + step, Math.ceil(max / step) * step);
    const labels = [], data = [];
    for (let b = start; b < end; b += step) {
      labels.push(`${b}–${b + step}`);
      data.push(vals.filter(v => v >= b && v < b + step).length);
    }
    charts[def.key] = new Chart(document.getElementById(def.canvas), {
      type: "bar",
      data: { labels, datasets: [{ label: "Consoles", data,
        backgroundColor: def.color, borderRadius: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8b97a7", font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: "#8b97a7", precision: 0 }, grid: { color: "#2a3140" }, beginAtZero: true }
        }
      }
    });
  }

  function renderTable(rows) {
    const q = state.search.toLowerCase();
    let view = rows;
    if (q) {
      view = rows.filter(r =>
        [r.owner, r.model, r.ram, r.notes].some(f => (f || "").toLowerCase().includes(q))
      );
    }
    view = view.slice().sort((a, b) => {
      const k = state.sortKey;
      let x = a[k], y = b[k];
      if (typeof x === "number" || typeof y === "number") {
        x = typeof x === "number" ? x : -Infinity;
        y = typeof y === "number" ? y : -Infinity;
        return (x - y) * state.sortDir;
      }
      return String(x || "").localeCompare(String(y || "")) * state.sortDir;
    });

    const tb = document.querySelector("#dataTable tbody");
    tb.innerHTML = "";
    view.forEach(r => {
      const tr = document.createElement("tr");
      const ram = (r.ram || "").trim();
      tr.innerHTML =
        `<td>${esc(r.owner)}</td>
         <td>${esc(r.model)}</td>
         <td class="num">${r.cpu ?? "—"}</td>
         <td class="num">${r.gpu ?? "—"}</td>
         <td class="num">${r.soc ?? "—"}</td>
         <td>${ram ? `<span class="ram-pill" style="background:${ramColor(ram)}">${esc(ram)}</span>` : "—"}</td>
         <td class="notes">${esc(r.notes)}</td>`;
      tb.appendChild(tr);
    });

    document.getElementById("tableTitle").textContent =
      `${PLATFORMS[state.platform].label} — ${state.consoleType}`;
    document.getElementById("rowCount").textContent =
      `${view.length} shown${q ? ` (of ${rows.length})` : ""}`;

    document.querySelectorAll("#dataTable th").forEach(th => {
      th.classList.remove("sorted-asc", "sorted-desc");
      if (th.dataset.key === state.sortKey)
        th.classList.add(state.sortDir === 1 ? "sorted-asc" : "sorted-desc");
    });
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function renderViewButtons() {
    document.querySelectorAll(".view-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.view === state.view);
    });
  }

  function fmtVolt(v) {
    if (v == null) return "—";
    if (v === "disabled") return "Off";
    return v;
  }

  // One point per frequency step: the submitted value if set, the computed
  // stock voltage if left on Auto and within CVB coverage, or null (a true
  // gap in the line) for a Disabled step or an Auto step with no coverage.
  function uvCurve(platform, freqs, r) {
    return freqs.map((f, i) => {
      const v = r.volts[i];
      if (v === "disabled") return null;
      if (v != null) return v;
      return autoVoltageFor(platform, i, r.gpu_speedo, r.voltage_offset || 0, r.vmin);
    });
  }

  function renderUvChart(rows) {
    const freqs = uvFreqs();
    const labels = freqs.map(f => `${Math.floor(f / 1000)}MHz`);

    if (charts.uv) charts.uv.destroy();
    if (!rows.length) { charts.uv = null; return; }

    const datasets = rows.map(r => {
      const color = ramColor(r.owner);
      return {
        label: r.owner,
        data: uvCurve(state.platform, freqs, r),
        borderColor: color, backgroundColor: color,
        pointRadius: 2, pointHoverRadius: 4, borderWidth: 1.5, tension: 0.15,
      };
    });

    charts.uv = new Chart(document.getElementById("uvChart"), {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { position: "right", labels: { color: "#e6edf3", boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y} mV` } },
        },
        scales: {
          x: { ticks: { color: "#8b97a7", font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: "#8b97a7" }, grid: { color: "#2a3140" },
               title: { display: true, text: "mV", color: "#8b97a7" } },
        },
      },
    });
  }

  function renderUvTable(rows) {
    const freqs = uvFreqs();
    const head = document.getElementById("uvTableHead");
    head.innerHTML =
      `<th>Owner</th><th class="num">GPU speedo</th><th>UV table</th><th class="num">Offset</th><th class="num">Vmin</th>` +
      freqs.map(f => `<th class="num uv-freq-col" title="${f} kHz">${Math.floor(f / 1000)}MHz</th>`).join("") +
      `<th>Notes</th>`;

    const tb = document.querySelector("#uvTable tbody");
    tb.innerHTML = "";
    rows.forEach(r => {
      const tr = document.createElement("tr");
      const offset = r.voltage_offset || 0;
      const cells = [
        `<td>${esc(r.owner)}</td>`,
        `<td class="num">${r.gpu_speedo ?? "—"}</td>`,
        `<td>${esc(r.uv_table || "None")}</td>`,
        `<td class="num">${offset > 0 ? "+" + offset : offset}</td>`,
        `<td class="num">${r.vmin ?? "—"}</td>`,
        ...freqs.map((f, i) => `<td class="num uv-freq-col">${fmtVolt(r.volts[i])}</td>`),
        `<td class="notes">${esc(r.notes)}</td>`,
      ];
      tr.innerHTML = cells.join("");
      tb.appendChild(tr);
    });

    document.getElementById("uvTableTitle").textContent =
      `${PLATFORMS[state.platform].label} — GPU UV tables`;
    document.getElementById("uvRowCount").textContent = `${rows.length} submissions`;
  }

  function render() {
    renderPlatformButtons();
    renderViewButtons();
    document.getElementById("tabs").classList.toggle("hidden", state.view !== "speedo");
    document.getElementById("speedoView").classList.toggle("hidden", state.view !== "speedo");
    document.getElementById("uvView").classList.toggle("hidden", state.view !== "uv");
    document.getElementById("addBtn").classList.toggle("hidden", state.view !== "speedo");
    document.querySelector("main").classList.toggle("main-wide", state.view === "uv");

    if (state.view === "speedo") {
      const entries = platformEntries();
      renderTabs(entries);
      const rows = filterByType(entries);
      renderStats(rows);
      SPEEDOS.forEach(def => renderSpeedoChart(def, rows));
      renderRamChart(rows);
      renderTable(rows);
      refreshModalOptions();
    } else {
      const uvRows = platformUvEntries();
      renderUvChart(uvRows);
      renderUvTable(uvRows);
      refreshUvModalOptions();
    }
  }

  /* ---------- add-entry modal → GitHub issue ---------- */

  function refreshModalOptions() {
    const models = PLATFORMS[state.platform].order;
    document.getElementById("modelSelect").innerHTML =
      models.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("");

    const rams = PLATFORMS[state.platform].ram;
    document.getElementById("ramSelect").innerHTML =
      `<option value="">— none / unknown —</option>` +
      rams.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
  }

  function openModal() { document.getElementById("modal").classList.remove("hidden"); }
  function closeModal() { document.getElementById("modal").classList.add("hidden"); }

  function refreshUvModalOptions() {
    const tables = PLATFORMS[state.platform].uvTables;
    document.getElementById("uvTableSelect").innerHTML =
      tables.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("");

    // Text (not number) input: besides an mV value, a step can be typed as
    // "disabled"/"off" — kept distinct from a blank field, which means Auto.
    const grid = document.getElementById("uvVoltsGrid");
    grid.innerHTML = uvFreqs().map(f =>
      `<label class="uv-volt-field"><span>${Math.floor(f / 1000)}MHz</span>
         <input type="text" inputmode="numeric" name="v_${f}" placeholder="Auto" /></label>`
    ).join("");
  }

  function openUvModal() { document.getElementById("uvModal").classList.remove("hidden"); }
  function closeUvModal() { document.getElementById("uvModal").classList.add("hidden"); }

  // Identity of an entry, for duplicate detection. Numbers and form strings
  // normalize the same way ("1680" === 1680, blank === null).
  function entryKey(e) {
    const n = v => (v === "" || v == null ? "" : String(Number(v)));
    return [
      (e.owner || "").trim().toLowerCase(), e.model || "",
      n(e.cpu), n(e.gpu), n(e.soc), (e.ram || "").trim(),
    ].join("|");
  }

  function onSubmit(e) {
    e.preventDefault();
    const f = new FormData(e.target);
    const cpu = (f.get("cpu") || "").trim();
    const gpu = (f.get("gpu") || "").trim();
    const soc = (f.get("soc") || "").trim();
    if (!cpu && !gpu && !soc) {
      alert("Enter at least one speedo value (CPU, GPU or SOC).");
      return;
    }

    const r = RANGES[state.platform];
    for (const [field, val] of [["cpu", cpu], ["gpu", gpu], ["soc", soc]]) {
      if (val && (Number(val) < r[field][0] || Number(val) > r[field][1])) {
        alert(`${field.toUpperCase()} speedo ${val} is outside the valid ` +
          `${PLATFORMS[state.platform].label} range (${r[field][0]}–${r[field][1]}).`);
        return;
      }
    }

    const candidate = { owner: f.get("owner"), model: f.get("model"), cpu, gpu, soc, ram: f.get("ram") };
    if (platformEntries().some(x => entryKey(x) === entryKey(candidate)) &&
        !confirm("An identical entry already exists in the database. Submit anyway?")) {
      return;
    }
    // GitHub issue-FORM dropdowns can't be prefilled via URL, so instead we open
    // a plain issue with the body pre-filled in the exact "### Heading\n\nvalue"
    // shape the workflow parser reads. Everything lands populated.
    const fields = [
      ["Platform", PLATFORMS[state.platform].label],
      ["Model", f.get("model") || ""],
      ["Owner / handle", (f.get("owner") || "").trim()],
      ["CPU speedo", cpu],
      ["GPU speedo", gpu],
      ["SOC speedo", soc],
      ["RAM bin", f.get("ram") || ""],
      ["Notes", (f.get("notes") || "").trim()],
    ];
    const body = fields
      .map(([h, v]) => `### ${h}\n\n${v || "_No response_"}`)
      .join("\n\n");
    const params = new URLSearchParams({
      title: `[Submission] ${PLATFORMS[state.platform].label} ${f.get("model") || ""}`.trim(),
      labels: "speedo-submission",
      body,
    });
    window.open(`https://github.com/${getRepo()}/issues/new?${params.toString()}`,
      "_blank", "noopener");
    e.target.reset();
    closeModal();
  }

  function onUvSubmit(e) {
    e.preventDefault();
    const f = new FormData(e.target);
    const gpu = (f.get("gpu_speedo") || "").trim();
    if (!gpu) { alert("GPU speedo is required."); return; }

    const r = RANGES[state.platform];
    if (Number(gpu) < r.gpu[0] || Number(gpu) > r.gpu[1]) {
      alert(`GPU speedo ${gpu} is outside the valid ` +
        `${PLATFORMS[state.platform].label} range (${r.gpu[0]}–${r.gpu[1]}).`);
      return;
    }

    const offsetRaw = (f.get("voltage_offset") || "0").trim();
    if (!/^-?\d+$/.test(offsetRaw)) { alert("Voltage offset must be a whole number."); return; }
    const offset = Number(offsetRaw);
    if (offset < UV_OFFSET_RANGE[0] || offset > UV_OFFSET_RANGE[1]) {
      alert(`Voltage offset ${offset} is outside the sane range ` +
        `(${UV_OFFSET_RANGE[0]}–${UV_OFFSET_RANGE[1]} mV).`);
      return;
    }
    const uvTable = f.get("uv_table") || "None";

    const vmin = (f.get("vmin") || "").trim();
    if (!vmin) { alert("Vmin is required."); return; }
    const vminRange = UV_VMIN_RANGE[state.platform];
    if (Number(vmin) < vminRange[0] || Number(vmin) > vminRange[1]) {
      alert(`Vmin ${vmin} is outside the valid ` +
        `${PLATFORMS[state.platform].label} range (${vminRange[0]}–${vminRange[1]}).`);
      return;
    }

    // Each per-step field is blank (Auto), "disabled"/"off" (Disabled — kept
    // distinct from Auto), or an mV number.
    const freqs = uvFreqs();
    const volts = freqs.map(fr => {
      const raw = (f.get(`v_${fr}`) || "").trim();
      if (raw === "") return null;
      if (/^(disabled|off)$/i.test(raw)) return "disabled";
      return Number(raw);
    });
    if (volts.every(v => v === null)) {
      alert("Enter at least one voltage value.");
      return;
    }
    for (let i = 0; i < volts.length; i++) {
      const v = volts[i];
      if (v === null || v === "disabled") continue;
      if (!Number.isFinite(v) || (v < UV_VOLT_RANGE[0] || v > UV_VOLT_RANGE[1])) {
        alert(`Voltage for ${Math.floor(freqs[i] / 1000)}MHz ('${f.get(`v_${freqs[i]}`)}') must be a ` +
          `number in the sane range (${UV_VOLT_RANGE[0]}–${UV_VOLT_RANGE[1]} mV), or "disabled".`);
        return;
      }
    }

    const voltsText = volts.map(v => (v === null ? "0" : String(v))).join(", ");
    const fields = [
      ["Platform", PLATFORMS[state.platform].label],
      ["Owner / handle", (f.get("owner") || "").trim()],
      ["GPU speedo", gpu],
      ["UV table", uvTable],
      ["Voltage offset", String(offset)],
      ["Vmin", vmin],
      ["Voltage table", voltsText],
      ["Notes", (f.get("notes") || "").trim()],
    ];
    const body = fields
      .map(([h, v]) => `### ${h}\n\n${v || "_No response_"}`)
      .join("\n\n");
    const params = new URLSearchParams({
      title: `[UV Submission] ${PLATFORMS[state.platform].label} GPU voltage table`.trim(),
      labels: "uv-submission",
      body,
    });
    window.open(`https://github.com/${getRepo()}/issues/new?${params.toString()}`,
      "_blank", "noopener");
    e.target.reset();
    closeUvModal();
  }

  /* ---------- wire up ---------- */

  function init() {
    document.getElementById("srcCount").textContent =
      (window.SPEEDO_DATA.mariko.length + window.SPEEDO_DATA.erista.length);

    document.querySelectorAll(".platform-btn").forEach(btn => {
      btn.onclick = () => {
        state.platform = btn.dataset.platform;
        state.consoleType = "Total";
        state.sortKey = PLATFORMS[state.platform].sort;  // platform's default metric
        state.sortDir = -1;
        render();
      };
    });

    document.getElementById("search").addEventListener("input", e => {
      state.search = e.target.value;
      renderTable(filterByType(platformEntries()));
    });

    document.querySelectorAll("#dataTable th").forEach(th => {
      th.onclick = () => {
        const k = th.dataset.key;
        if (state.sortKey === k) state.sortDir *= -1;
        else { state.sortKey = k; state.sortDir = ["cpu", "gpu", "soc"].includes(k) ? -1 : 1; }
        renderTable(filterByType(platformEntries()));
      };
    });

    document.querySelectorAll(".view-btn").forEach(btn => {
      btn.onclick = () => { state.view = btn.dataset.view; render(); };
    });

    document.getElementById("addBtn").onclick = openModal;
    document.getElementById("cancelBtn").onclick = closeModal;
    document.getElementById("addForm").addEventListener("submit", onSubmit);
    document.getElementById("modal").addEventListener("click", e => {
      if (e.target.id === "modal") closeModal();
    });

    document.getElementById("addUvBtn").onclick = openUvModal;
    document.getElementById("uvCancelBtn").onclick = closeUvModal;
    document.getElementById("uvForm").addEventListener("submit", onUvSubmit);
    document.getElementById("uvModal").addEventListener("click", e => {
      if (e.target.id === "uvModal") closeUvModal();
    });

    document.addEventListener("keydown", e => {
      if (e.key === "Escape") { closeModal(); closeUvModal(); }
    });

    render();
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
