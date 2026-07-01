/* SpeedoDB — client-side app. Data comes from window.SPEEDO_DATA (data.js),
   generated from data/entries.csv. New entries are submitted as GitHub issues
   (see "Add entry"), which a workflow validates and commits to the dataset. */
(function () {
  "use strict";

  const PLATFORMS = {
    // sort: default table sort key for the platform. Erista defaults to GPU
    // speedo, which is the more reliable metric on those units; Mariko uses SOC.
    mariko: { label: "Mariko", order: ["OLED", "V2", "Lite"], sort: "soc",
      ram: ["AA-MGCL", "AB-MGCL", "AM-MGCJ", "NEE", "NME", "WT:B", "WT:E", "WT:F"] },
    erista: { label: "Erista", order: ["V1 Unpatched", "V1 Patched"], sort: "gpu",
      ram: ["HB-MGCH", "NLE", "WT:C"] },
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
  };

  const charts = { cpu: null, gpu: null, soc: null, ram: null };

  /* ---------- data helpers ---------- */

  function platformEntries() {
    return window.SPEEDO_DATA[state.platform] || [];
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

  function render() {
    const entries = platformEntries();
    renderPlatformButtons();
    renderTabs(entries);
    const rows = filterByType(entries);
    renderStats(rows);
    SPEEDOS.forEach(def => renderSpeedoChart(def, rows));
    renderRamChart(rows);
    renderTable(rows);
    refreshModalOptions();
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

    document.getElementById("addBtn").onclick = openModal;
    document.getElementById("cancelBtn").onclick = closeModal;
    document.getElementById("addForm").addEventListener("submit", onSubmit);
    document.getElementById("modal").addEventListener("click", e => {
      if (e.target.id === "modal") closeModal();
    });
    document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

    render();
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
