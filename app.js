/* ════════════════════════════════════════════════════════════════
   AgriGrant Dashboard — frontend engine
   Renders category-organized widgets driven by the backend payload.
   Each widget kind has an entry in RENDERERS. Widgets can be added,
   deleted (hidden), and minimized; the sidebar filters by category.
   ════════════════════════════════════════════════════════════════ */

const C = {
  greenDark: "#1e5c2e", greenMid: "#2e7d46", greenLight: "#52a869",
  greenPale: "#a8d5b5", gold: "#c8991a", amber: "#e8b84b",
  red: "#c0392b", blue: "#2471a3", muted: "#6b7e72",
};
const cropColors = [C.gold, C.greenMid, C.amber, C.greenLight, C.blue, C.red, C.muted];
const CAT_COLORS = {
  purpose: C.greenDark, community: C.gold, csa: C.greenLight, yields: C.greenMid,
  sustainability: C.greenLight, economics: C.blue, grants: C.amber,
  tasks: C.red, map: C.muted,
};
const statusLabel = {
  "on-track": "On Track", "at-risk": "At Risk", "delayed": "Delayed",
  "complete": "Complete", "pending": "Pending",
};
const pinClass = {
  "on-track": "pin-green", "at-risk": "pin-amber", "delayed": "pin-red",
  "complete": "pin-blue", "pending": "pin-grey",
};
const taskStatusLabel = {
  todo: "To Do", "in-progress": "In Progress", blocked: "Blocked", done: "Done",
};

const fmt = n => Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

/* ── App state ──────────────────────────────────────── */
let DATA = null;
let activeCategory = "all";       // sidebar selection
let density = "all";              // "all" | "focus"
let filters = { crop: "", status: "" };
const charts = {};                // live Chart.js instances by widget id
let lastPayload = "";

/* ── Helpers ────────────────────────────────────────── */
function toast(msg, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.toggle("error", isError);
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), 2200);
}
async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || res.statusText);
  return json;
}
function applyFilters(plots) {
  return plots.filter(p =>
    (!filters.crop || p.crop === filters.crop) &&
    (!filters.status || p.status === filters.status));
}

/* ════════════════════════════════════════════════════
   WIDGET RENDERERS — one per "kind" in the catalog.
   Each returns an HTML string for the card body, and may
   register a post-render hook in `mount` to draw charts.
   ════════════════════════════════════════════════════ */
const RENDERERS = {

  /* ---- Community ---- */
  community_kpis(d) {
    const k = d.kpis;
    const cells = [
      ["Produce Distributed", fmt(k.lbs_distributed), "lbs", "pounds YTD"],
      ["Families Served", fmt(k.families_served), "families", "peak / month"],
      ["Volunteer Hours", fmt(k.volunteer_hours), "hrs", "hours YTD"],
      ["CSA Shares", fmt(k.csa_shares), "shares", "active"],
    ];
    return `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:18px">
      ${cells.map(([t, v, u, s]) => `<div>
        <div class="kpi-sub" style="font-weight:700;text-transform:uppercase;letter-spacing:.5px;font-size:10px">${t}</div>
        <div class="kpi-value" style="font-size:26px;margin-top:4px">${v}<span class="kpi-unit"> ${u}</span></div>
        <div class="kpi-sub">${s}</div></div>`).join("")}
    </div>`;
  },

  community_table(d) {
    const rows = d.community.map(r => `<tr>
      <td><strong>${d.months[r.month-1]}</strong></td>
      <td>${fmt(r.lbs_dist)}</td><td>${r.families}</td>
      <td>${fmt(r.volunteer_hrs)}</td><td>${r.csa_shares}</td></tr>`).join("");
    return `<div class="scroll-y"><table class="data-table">
      <thead><tr><th>Month</th><th>Produce (lbs)</th><th>Families</th><th>Volunteer (hrs)</th><th>CSA (shares)</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  },

  line_produce(d, id) {
    return `<canvas id="cv-${id}" height="170"></canvas>`;
  },

  /* ---- Yields ---- */
  kpi_yield(d) {
    const plots = applyFilters(d.plots);
    const total = plots.reduce((s, p) => s + p.yield_bu, 0);
    const crops = new Set(plots.map(p => p.crop)).size;
    return `<div class="kpi-value">${fmt(total)}<span class="kpi-unit"> lbs</span></div>
      <div class="kpi-sub">Across ${crops} crops · ${fmt(plots.reduce((s,p)=>s+p.acres,0))} acres</div>`;
  },
  yield_line(d, id) { return `<canvas id="cv-${id}" height="180"></canvas>`; },
  crop_pie(d, id) { return `<canvas id="cv-${id}" height="200"></canvas>`; },
  plot_table(d) {
    const plots = applyFilters(d.plots);
    const rows = plots.map(p => `<tr>
      <td><strong>${esc(p.id)}</strong></td><td>${esc(p.crop)}</td>
      <td>${fmt(p.acres)}</td><td>${p.yield_bu > 0 ? fmt(p.yield_bu) : "—"}</td>
      <td><span class="status-pill pill-${p.status}">${statusLabel[p.status] || p.status}</span></td>
    </tr>`).join("") || `<tr><td colspan="5" style="color:var(--muted)">No plots match filters</td></tr>`;
    return `<div class="scroll-y"><table class="data-table">
      <thead><tr><th>Bed</th><th>Crop</th><th>Area (acres)</th><th>Yield (lbs)</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  },

  /* ---- Sustainability ---- */
  kpi_carbon(d) {
    return `<div class="kpi-value">${fmt(d.kpis.carbon_kg)}<span class="kpi-unit"> kg</span></div>
      <div class="kpi-sub">CO₂ sequestered · carbon-credit ready</div>`;
  },
  kpi_water(d) {
    return `<div class="kpi-value">${fmt(d.kpis.water_gal)}<span class="kpi-unit"> gal</span></div>
      <div class="kpi-sub">Irrigation water used YTD</div>`;
  },
  kpi_solar(d) {
    return `<div class="kpi-value">${fmt(d.kpis.solar_kwh)}<span class="kpi-unit"> kWh</span></div>
      <div class="kpi-sub">On-site solar generation YTD</div>`;
  },
  moisture_gauge(d, id) {
    return `<div class="gauge-wrap"><canvas id="cv-${id}"></canvas></div>
      <div style="text-align:center;font-size:12px;color:var(--muted)">
        <span>${Math.round(d.kpis.soil_moisture)}%</span> VWC · Target 35–50%</div>`;
  },
  sustain_line(d, id) { return `<canvas id="cv-${id}" height="180"></canvas>`; },
  inputs_chart(d, id) { return `<canvas id="cv-${id}" height="190"></canvas>`; },

  /* ---- Economics ---- */
  econ_table(d) {
    const rows = d.economics.map(e => {
      const profit = e.revenue - e.cost;
      const margin = e.revenue ? Math.round(profit / e.revenue * 100) : 0;
      const cls = profit >= 0 ? "pill-on-track" : "pill-delayed";
      return `<tr><td><strong>${esc(e.crop)}</strong></td>
        <td>$${fmt(e.cost)}</td><td>$${fmt(e.revenue)}</td>
        <td>$${fmt(profit)}</td>
        <td><span class="status-pill ${cls}">${margin}%</span></td>
        <td style="color:var(--muted)">${esc(e.unit)}</td></tr>`;
    }).join("");
    return `<div class="scroll-y"><table class="data-table">
      <thead><tr><th>Crop</th><th>Cost</th><th>Revenue</th><th>Profit</th><th>Margin</th><th>Per</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  },
  margin_chart(d, id) { return `<canvas id="cv-${id}" height="190"></canvas>`; },

  /* ---- Grants & Budget ---- */
  kpi_utilization(d) {
    const k = d.kpis;
    return `<div class="kpi-value">${k.utilization_pct}%</div>
      <div class="kpi-sub">$${fmt(k.spent)} of $${fmt(k.grant_total)} awarded</div>`;
  },
  budget_chart(d, id) { return `<canvas id="cv-${id}" height="180"></canvas>`; },
  budget_progress(d) {
    const colors = [C.greenMid, C.greenDark, C.greenLight, C.gold, C.amber, C.muted];
    return d.budget.map((b, i) => {
      const pct = b.allocated ? Math.round(b.spent / b.allocated * 100) : 0;
      return `<div class="progress-row">
        <div class="progress-label"><span>${esc(b.category)}</span><span>${pct}%</span></div>
        <div class="progress-bar"><div class="progress-fill"
          style="width:${Math.min(pct,100)}%;background:${colors[i%colors.length]}"></div></div></div>`;
    }).join("");
  },
  timeline(d) {
    return `<div class="timeline">${d.milestones.map(m => `
      <div class="tl-item"><div class="tl-dot ${m.state}"></div>
        <div class="tl-body"><h4>${esc(m.label)}</h4><p>${esc(m.date)}</p></div></div>`).join("")}</div>`;
  },

  /* ---- Project Management ---- */
  task_table(d) {
    const order = { "in-progress": 0, blocked: 1, todo: 2, done: 3 };
    const tasks = [...d.tasks].sort((a, b) => (order[a.status] - order[b.status]) || a.due.localeCompare(b.due));
    const rows = tasks.map(t => `<tr>
      <td>${esc(t.title)}</td>
      <td>${esc(t.assignee) || "—"}</td>
      <td style="color:var(--muted)">${esc(t.due) || "—"}</td>
      <td><span class="prio-pill prio-${t.priority}">${t.priority}</span></td>
      <td><span class="status-pill pill-${t.status}">${taskStatusLabel[t.status] || t.status}</span></td>
    </tr>`).join("") || `<tr><td colspan="5" style="color:var(--muted)">No tasks — add some in Manage Data</td></tr>`;
    return `<div class="scroll-y"><table class="data-table">
      <thead><tr><th>Task</th><th>Assignee</th><th>Due</th><th>Priority</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  },
  deadline_list(d) {
    if (!d.deadlines.length) return `<div style="color:var(--muted);font-size:13px">No upcoming deadlines</div>`;
    return d.deadlines.map(dl => `<div class="deadline-item">
      <div class="deadline-date">${esc(dl.due)}</div>
      <div><div style="font-size:13px;font-weight:600">${esc(dl.item)}</div>
      <div class="deadline-grant">${esc(dl.grant)}</div></div></div>`).join("");
  },

  /* ---- Field Map ---- */
  field_map(d) {
    const plots = applyFilters(d.plots);
    return `<div class="map-placeholder"><div class="map-pins">
      ${plots.map(p => `<div class="pin ${pinClass[p.status] || "pin-grey"}"
        data-label="${esc(p.id)} — ${esc(p.crop)}"
        style="top:${p.y_pct}%;left:${p.x_pct}%"></div>`).join("")}</div>
      <div style="position:absolute;bottom:8px;left:8px;display:flex;gap:8px;font-size:11px;color:#1a2a1e">
        <span>🟢 On Track</span><span>🟡 At Risk</span><span>🔴 Delayed</span><span>🔵 Complete</span></div>
    </div>`;
  },

  /* ---- Project Management: Milestone Roadmap ---- */
  roadmap(d) {
    const items = d.roadmap || [];
    if (!items.length) return `<div style="color:var(--muted);font-size:13px">No roadmap items yet — add them in Manage Data.</div>`;
    const phases = [];
    items.forEach(r => {
      let p = phases.find(x => x.phase === r.phase);
      if (!p) { p = { phase: r.phase, rows: [] }; phases.push(p); }
      p.rows.push(r);
    });
    const rmStatus = { todo: "To Do", "in-progress": "In Progress", done: "Done" };
    const rmPill = { todo: "pill-todo", "in-progress": "pill-in-progress", done: "pill-done" };
    return `<div class="roadmap">${phases.map(p => `
      <div class="rm-phase">
        <div class="rm-phase-head">${esc(p.phase)}</div>
        ${p.rows.map(r => `<div class="rm-item">
          <span class="cat-tag cat-${esc(r.category)}">${esc(r.category)}</span>
          <div class="rm-main">
            <div class="rm-title">${esc(r.item)}</div>
            ${r.detail ? `<div class="rm-detail">${esc(r.detail)}</div>` : ""}
          </div>
          <div class="rm-side">
            <span class="status-pill ${rmPill[r.status] || "pill-todo"}">${rmStatus[r.status] || r.status}</span>
            <span class="rm-due">${esc(r.due)}</span>
          </div>
        </div>`).join("")}
      </div>`).join("")}</div>`;
  },

  /* ---- Purpose & Practice (embodiment layer) ---- */
  foundations(d) {
    const f = (d.embodiment && d.embodiment.foundations) || [];
    return `<div class="embody-grid">${f.map(x => `
      <div class="embody-card">
        <div class="embody-name">${esc(x.name)}</div>
        <div class="embody-practice">${esc(x.practice)}</div>
        <div class="embody-text">${esc(x.meaning)}</div>
        <div class="embody-felt">“${esc(x.embodied)}”</div>
      </div>`).join("")}</div>`;
  },
  perfections(d) {
    const p = (d.embodiment && d.embodiment.perfections) || [];
    return `<div class="scroll-y"><table class="data-table">
      <thead><tr><th>Perfection</th><th>In the field</th><th>What it trains</th></tr></thead>
      <tbody>${p.map(x => `<tr>
        <td><strong>${esc(x.name)}</strong></td>
        <td>${esc(x.field)}</td>
        <td style="color:var(--muted)">${esc(x.trains)}</td></tr>`).join("")}</tbody>
    </table></div>`;
  },
  curriculum(d) {
    const c = (d.embodiment && d.embodiment.curriculum) || [];
    const phases = [];
    c.forEach(r => {
      let p = phases.find(x => x.phase === r.phase);
      if (!p) { p = { phase: r.phase, rows: [] }; phases.push(p); }
      p.rows.push(r);
    });
    return `<div class="curriculum">${phases.map(p => `
      <div class="cur-phase">
        <div class="cur-phase-head">${esc(p.phase)}</div>
        ${p.rows.map(r => `<div class="cur-week">
          <div class="cur-wk">Wk ${r.week}</div>
          <div class="cur-body">
            <div class="cur-anchor">${esc(r.anchor)}</div>
            <div class="cur-task">${esc(r.task)}</div>
            <div class="cur-prompt">Reflection: “${esc(r.prompt)}”</div>
          </div>
        </div>`).join("")}
      </div>`).join("")}</div>`;
  },
  reflection(d) {
    const list = (d.embodiment && d.embodiment.reflections) || ["What did the soil teach you today?"];
    // Rotate by ISO week so the prompt changes through the season.
    const now = new Date();
    const wk = Math.floor((now - new Date(now.getFullYear(), 0, 1)) / (7 * 864e5));
    const prompt = list[wk % list.length];
    const tagline = (d.embodiment && d.embodiment.tagline) || "";
    return `<div class="reflect">
      <div class="reflect-mark">❝</div>
      <div class="reflect-prompt">${esc(prompt)}</div>
      <div class="reflect-note">${esc(tagline)}</div>
    </div>`;
  },

  /* ---- CSA Program ---- */
  csa_kpis(d) {
    const s = d.csa.summary;
    const cells = [
      ["Total Orders", fmt(s.total_orders), "orders", `${d.csa.orders.length ? "since " + fmtDate(s.date_range[0]) : ""}`],
      ["Repeat Customers", fmt(s.repeat_customers), "of " + s.unique_customers, `${s.repeat_pct}% came back`],
      ["Most Popular Share", s.most_popular_share, "", `${fmt(s.share_counts[s.most_popular_share] || 0)} sold`],
      ["Est. CSA Revenue", "$" + fmt(s.grand_total_revenue), "total", "editable prices"],
    ];
    return `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:18px">
      ${cells.map(([t, v, u, sub]) => `<div>
        <div class="kpi-sub" style="font-weight:700;text-transform:uppercase;letter-spacing:.5px;font-size:10px">${t}</div>
        <div class="kpi-value" style="font-size:24px;margin-top:4px">${esc(String(v))}<span class="kpi-unit"> ${esc(u)}</span></div>
        <div class="kpi-sub">${esc(sub)}</div></div>`).join("")}
    </div>`;
  },
  csa_orders_line(d, id) { return `<canvas id="cv-${id}" height="180"></canvas>`; },
  csa_shares_pie(d, id) { return `<canvas id="cv-${id}" height="200"></canvas>`; },
  csa_monthly_sales(d, id) { return `<canvas id="cv-${id}" height="180"></canvas>`; },
  csa_orders_table(d) {
    // A concise preview here; the full breakdown is in the expand view.
    const orders = [...d.csa.orders].slice(-12).reverse();
    const rows = orders.map(o => `<tr>
      <td>${fmtDate(o.order_date)}</td>
      <td><strong>${esc(o.customer)}</strong></td>
      <td>${esc(shortLoc(o.location))}</td>
      <td>${esc(itemsSummary(o))}</td></tr>`).join("");
    return `<div class="scroll-y"><table class="data-table">
      <thead><tr><th>Date</th><th>Customer</th><th>Location</th><th>Order</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <div class="tbl-note">Showing latest 12 of ${d.csa.orders.length} orders — expand ⤢ for the full breakdown.</div>`;
  },
};

/* ── CSA helpers ─────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return "—";
  const dt = new Date(iso + "T00:00:00");
  return isNaN(dt) ? iso : dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
function monthLabel(ym) {
  if (!ym || ym.indexOf("-") < 0) return ym || "—";
  const [y, m] = ym.split("-");
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}
function shortLoc(loc) {
  if (!loc) return "—";
  if (loc.includes("Miami Dade College")) return "MDC North Campus";
  if (loc.includes("Barry")) return "Barry University";
  if (loc.includes("Home")) return "Home delivery";
  if (loc.includes("Cerasee")) return "Cerasee Farm";
  return loc.length > 24 ? loc.slice(0, 23) + "…" : loc;
}
function itemsSummary(o) {
  const items = o.items_map || {};
  const parts = Object.entries(items).map(([k, v]) => `${v}× ${k}`);
  return parts.join(", ") || "—";
}

/* ════════════════════════════════════════════════════
   CHART MOUNTERS — run after a widget's HTML is in the DOM.
   ════════════════════════════════════════════════════ */
const MOUNTERS = {
  line_produce(d, id) {
    drawLine(id, d.months, [{
      label: "Lbs distributed", data: d.community.map(r => r.lbs_dist),
      borderColor: C.gold, fill: true,
    }], "Pounds (lbs)");
  },
  yield_line(d, id) {
    const crops = Object.keys(d.monthly_yield.series);
    drawLine(id, d.monthly_yield.labels, crops.map((crop, i) => ({
      label: crop, data: d.monthly_yield.series[crop],
      borderColor: cropColors[i % cropColors.length],
    })), "Yield (lbs)");
  },
  crop_pie(d, id) {
    const plots = applyFilters(d.plots);
    const acreage = {};
    plots.forEach(p => acreage[p.crop] = (acreage[p.crop] || 0) + p.acres);
    makeChart(id, {
      type: "doughnut",
      data: {
        labels: Object.entries(acreage).map(([c, a]) => `${c} (${fmt(a)} ac)`),
        datasets: [{ data: Object.values(acreage), backgroundColor: cropColors, borderColor: "#fff", borderWidth: 3 }],
      },
      options: { responsive: true, cutout: "55%",
        plugins: { legend: { position: "right", labels: { font: { size: 11 }, padding: 10 } } } },
    });
  },
  moisture_gauge(d, id) {
    const m = Math.max(0, Math.min(100, d.kpis.soil_moisture));
    makeChart(id, {
      type: "doughnut",
      data: { datasets: [{ data: [m, 100 - m], backgroundColor: [C.blue, "#e8f4fd"],
        borderWidth: 0, circumference: 270, rotation: -135 }] },
      options: { cutout: "72%", responsive: true,
        plugins: { legend: { display: false }, tooltip: { enabled: false } } },
      plugins: [{
        id: "gt", afterDraw(ch) {
          const { ctx, chartArea: { top, bottom, left, right } } = ch;
          ctx.save(); ctx.font = "bold 22px Segoe UI"; ctx.fillStyle = C.blue;
          ctx.textAlign = "center";
          ctx.fillText(Math.round(ch.data.datasets[0].data[0]) + "%", (left + right) / 2, (top + bottom) / 2 + 18);
          ctx.restore();
        },
      }],
    });
  },
  sustain_line(d, id) {
    drawLine(id, d.months, [
      { label: "Carbon (kg CO₂)", data: d.sustainability.map(r => r.carbon_kg), borderColor: C.greenMid, fill:false },
      { label: "Solar (kWh)", data: d.sustainability.map(r => r.solar_kwh), borderColor: C.amber, fill:false },
      { label: "Water (×100 gal)", data: d.sustainability.map(r => r.water_gal/100), borderColor: C.blue, fill:false },
    ], "kg CO₂ · kWh · ×100 gal");
  },
  inputs_chart(d, id) {
    makeChart(id, {
      type: "bar",
      data: {
        labels: d.inputs.map(i => i.name),
        datasets: [
          { label: "Applied", data: d.inputs.map(i => i.applied), backgroundColor: C.greenMid, borderRadius: 4 },
          { label: "Benchmark", data: d.inputs.map(i => i.benchmark), backgroundColor: C.greenPale, borderRadius: 4 },
        ],
      },
      options: { indexAxis: "y", responsive: true,
        plugins: { legend: { position: "top", labels: { font: { size: 11 } } } },
        scales: { x: { grid: { color: "#e8efe9" }, ticks: { font: { size: 11 } },
                       title: { display: true, text: "Level (ppm / index)", font: { size: 11 }, color: "#6b7e72" } },
                  y: { grid: { display: false }, ticks: { font: { size: 11 } } } } },
    });
  },
  budget_chart(d, id) {
    makeChart(id, {
      type: "bar",
      data: {
        labels: d.budget.map(b => b.category),
        datasets: [
          { label: "Allocated ($k)", data: d.budget.map(b => b.allocated / 1000), backgroundColor: C.greenPale, borderColor: C.greenMid, borderWidth: 1, borderRadius: 4 },
          { label: "Spent ($k)", data: d.budget.map(b => b.spent / 1000), backgroundColor: C.greenMid, borderColor: C.greenDark, borderWidth: 1, borderRadius: 4 },
        ],
      },
      options: { responsive: true,
        plugins: { legend: { position: "top", labels: { font: { size: 11 } } } },
        scales: { x: { grid: { display: false } },
                  y: { ticks: { callback: v => "$" + v + "k" }, grid: { color: "#e8efe9" },
                       title: { display: true, text: "USD (thousands)", font: { size: 11 }, color: "#6b7e72" } } } },
    });
  },
  margin_chart(d, id) {
    const sorted = [...d.economics].sort((a, b) => (b.revenue - b.cost) - (a.revenue - a.cost));
    makeChart(id, {
      type: "bar",
      data: {
        labels: sorted.map(e => e.crop),
        datasets: [{ label: "Profit ($)", data: sorted.map(e => e.revenue - e.cost),
          backgroundColor: sorted.map(e => e.revenue - e.cost >= 0 ? C.greenMid : C.red), borderRadius: 4 }],
      },
      options: { responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false } },
                  y: { ticks: { callback: v => "$" + v }, grid: { color: "#e8efe9" },
                       title: { display: true, text: "Profit (USD / season)", font: { size: 11 }, color: "#6b7e72" } } } },
    });
  },
  csa_orders_line(d, id) {
    const m = d.csa.summary.monthly;
    makeChart(id, {
      type: "bar",
      data: { labels: m.map(x => monthLabel(x.month)),
        datasets: [{ label: "Orders", data: m.map(x => x.orders), backgroundColor: C.greenMid, borderRadius: 4 }] },
      options: { responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false }, title: { display: true, text: "Month", font: { size: 11 }, color: "#6b7e72" } },
                  y: { beginAtZero: true, grid: { color: "#e8efe9" },
                       title: { display: true, text: "Orders", font: { size: 11 }, color: "#6b7e72" } } } },
    });
  },
  csa_shares_pie(d, id) {
    const sc = d.csa.summary.share_counts;
    const labels = Object.keys(sc), data = Object.values(sc);
    makeChart(id, {
      type: "doughnut",
      data: { labels: labels.map((l, i) => `${l} (${data[i]})`),
        datasets: [{ data, backgroundColor: [C.greenMid, C.gold, C.blue], borderColor: "#fff", borderWidth: 3 }] },
      options: { responsive: true, cutout: "55%",
        plugins: { legend: { position: "right", labels: { font: { size: 11 }, padding: 10 } } } },
    });
  },
  csa_monthly_sales(d, id) {
    const m = d.csa.summary.monthly;
    makeChart(id, {
      type: "bar",
      data: { labels: m.map(x => monthLabel(x.month)),
        datasets: [{ label: "Est. sales ($)", data: m.map(x => Math.round(x.revenue)), backgroundColor: C.gold, borderRadius: 4 }] },
      options: { responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false }, title: { display: true, text: "Month", font: { size: 11 }, color: "#6b7e72" } },
                  y: { beginAtZero: true, ticks: { callback: v => "$" + v }, grid: { color: "#e8efe9" },
                       title: { display: true, text: "Estimated sales (USD)", font: { size: 11 }, color: "#6b7e72" } } } },
    });
  },
};

/* ── Chart helpers ──────────────────────────────────── */
// Charts normally mount into the grid canvas "cv-<id>". The expand modal
// reuses the same MOUNTERS but points them at "dcv-<id>" via CANVAS_PREFIX,
// keeping its chart instances in a separate store so the two never collide.
let CANVAS_PREFIX = "cv-";
const detailCharts = {};
function makeChart(id, config) {
  const el = document.getElementById(CANVAS_PREFIX + id);
  if (!el) return;
  const store = CANVAS_PREFIX === "cv-" ? charts : detailCharts;
  if (store[id]) store[id].destroy();
  store[id] = new Chart(el, config);
}
function drawLine(id, labels, datasets, yUnit) {
  makeChart(id, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map(ds => ({
        tension: .4, pointRadius: 2,
        backgroundColor: "rgba(46,125,70,.06)",
        fill: ds.fill ?? true, ...ds,
      })),
    },
    options: { responsive: true,
      plugins: { legend: { position: "top", labels: { font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, title: { display: true, text: "Month", font: { size: 11 }, color: "#6b7e72" } },
        y: { grid: { color: "#e8efe9" },
             title: { display: !!yUnit, text: yUnit || "", font: { size: 11 }, color: "#6b7e72" } },
      } },
  });
}

/* ════════════════════════════════════════════════════
   RENDER PIPELINE
   ════════════════════════════════════════════════════ */
function visibleWidgets(d) {
  return d.widgets
    .filter(w => w.visible && d.catalog[w.wid])
    .filter(w => activeCategory === "all" || d.catalog[w.wid].category === activeCategory);
}

// In "focused" density we show only the headline KPI/visual per category.
const FOCUS_SET = new Set([
  "field_reflection", "community_kpis", "yield_line", "sustainability_trend",
  "econ_table", "grant_kpi", "task_board", "field_map",
]);

function renderGrid() {
  const d = DATA;
  const grid = document.getElementById("grid");
  Object.values(charts).forEach(ch => ch.destroy());
  for (const k in charts) delete charts[k];

  let widgets = visibleWidgets(d);
  if (density === "focus") widgets = widgets.filter(w => FOCUS_SET.has(w.wid));

  if (!widgets.length) {
    grid.innerHTML = `<div class="empty">No widgets to show here.<br>
      Use <strong>＋ Add Widget</strong> or switch category in the sidebar.</div>`;
    return;
  }

  grid.innerHTML = widgets.map(w => {
    const meta = d.catalog[w.wid];
    const renderer = RENDERERS[meta.kind];
    const body = renderer ? renderer(d, w.wid) : `<div style="color:var(--muted)">Unknown widget</div>`;
    const dot = CAT_COLORS[meta.category] || C.muted;
    const min = w.minimized ? "minimized" : "";
    const minIcon = w.minimized ? "▢" : "—";
    // Human anchor: every widget carries a line tying the number back to
    // people, labor, and living soil — data is never left to stand alone.
    const human = meta.human
      ? `<div class="card-human">🌱 ${esc(meta.human)}</div>` : "";
    return `<div class="card span-${meta.span} ${min}" data-wid="${w.wid}">
      <div class="card-head">
        <span class="card-cat-dot" style="background:${dot}"></span>
        <span class="card-title">${esc(meta.title)}</span>
        <button class="wbtn" title="Expand — full data & source"
          onclick="openDetail('${w.wid}')">⤢</button>
        <button class="wbtn" title="${w.minimized ? "Show" : "Collapse"}"
          onclick="toggleMinimize('${w.wid}', ${w.minimized ? 0 : 1})">${minIcon}</button>
        <button class="wbtn" title="Remove widget" onclick="removeWidget('${w.wid}')">✕</button>
      </div>
      <div class="card-body">${body}${human}</div>
    </div>`;
  }).join("");

  // Mount charts for non-minimized widgets
  widgets.forEach(w => {
    if (w.minimized) return;
    const meta = d.catalog[w.wid];
    if (MOUNTERS[meta.kind]) MOUNTERS[meta.kind](d, w.wid);
  });
}

/* ── Sidebar ────────────────────────────────────────── */
function renderSidebar() {
  const d = DATA;
  const counts = {};
  d.widgets.filter(w => w.visible).forEach(w => {
    const cat = d.catalog[w.wid]?.category;
    if (cat) counts[cat] = (counts[cat] || 0) + 1;
  });
  const totalVisible = d.widgets.filter(w => w.visible).length;

  const items = [{ id: "all", label: "All Widgets", icon: "▦", n: totalVisible }]
    .concat(d.categories.map(c => ({ id: c.id, label: c.label, icon: c.icon, n: counts[c.id] || 0 })));

  document.getElementById("nav-list").innerHTML = items.map(it => `
    <div class="nav-item ${activeCategory === it.id ? "active" : ""}" onclick="selectCategory('${it.id}')">
      <span class="nicon">${it.icon}</span><span>${it.label}</span>
      <span class="ncount">${it.n}</span></div>`).join("");
}

function selectCategory(cat) {
  activeCategory = cat;
  const d = DATA;
  const meta = cat === "all"
    ? { label: "All Widgets",
        crumb: (d.embodiment && d.embodiment.tagline) || "Every active widget across all categories" }
    : (() => { const c = d.categories.find(x => x.id === cat);
        return { label: `${c.icon} ${c.label}`, crumb: c.principle || `Widgets in the ${c.label} category` }; })();
  document.getElementById("view-title").textContent = meta.label;
  document.getElementById("view-crumbs").textContent = meta.crumb;
  renderSidebar();
  renderGrid();
  document.getElementById("sidebar").classList.remove("open");
}

/* ── Widget actions ─────────────────────────────────── */
async function toggleMinimize(wid, minimized) {
  try {
    await api("PUT", `/api/widgets/${wid}`, { minimized });
    const w = DATA.widgets.find(x => x.wid === wid);
    if (w) w.minimized = minimized;
    renderGrid();
  } catch (e) { toast(e.message, true); }
}
async function removeWidget(wid) {
  try {
    await api("DELETE", `/api/widgets/${wid}`);
    const w = DATA.widgets.find(x => x.wid === wid);
    if (w) w.visible = 0;
    toast(`Removed "${DATA.catalog[wid].title}"`);
    renderSidebar(); renderGrid();
  } catch (e) { toast(e.message, true); }
}
async function addWidget(wid) {
  try {
    await api("POST", "/api/widgets", { wid });
    toast(`Added "${DATA.catalog[wid].title}"`);
    await refresh(true);
    renderCatalog();
  } catch (e) { toast(e.message, true); }
}
async function restoreAll() {
  const hidden = DATA.widgets.filter(w => !w.visible);
  if (!hidden.length) return toast("No hidden widgets");
  try {
    for (const w of hidden) await api("POST", "/api/widgets", { wid: w.wid });
    toast(`Restored ${hidden.length} widget(s)`);
    await refresh(true);
  } catch (e) { toast(e.message, true); }
}

/* ════════════════════════════════════════════════════
   EXPAND → full data + source. Replaces the old expand
   behavior. Opening a widget shows its enlarged visual,
   the complete underlying data table, a link to the
   Google Sheet / Excel it came from, and the human anchor.
   ════════════════════════════════════════════════════ */
const SYNCABLE = new Set(["plots", "budget", "monthly_yield", "inputs",
                          "community", "sustainability", "economics"]);

function simpleTable(headers, rows) {
  if (!rows.length) return `<div style="color:var(--muted);font-size:13px">No data yet.</div>`;
  return `<div class="scroll-y"><table class="data-table">
    <thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

// Build the complete underlying data table for a widget's source dataset.
function detailTable(wid, d) {
  const src = d.catalog[wid].source;
  switch (src) {
    case "community":
      return simpleTable(["Month", "Produce (lbs)", "Families", "Volunteer (hrs)", "CSA (shares)"],
        d.community.map(r => [d.months[r.month-1], fmt(r.lbs_dist), r.families, fmt(r.volunteer_hrs), r.csa_shares]));
    case "monthly_yield": {
      const crops = Object.keys(d.monthly_yield.series);
      return simpleTable(["Month", ...crops.map(c => c + " (lbs)")],
        d.monthly_yield.labels.map((m, i) => [m, ...crops.map(c => fmt(d.monthly_yield.series[c][i]))]));
    }
    case "plots":
      return simpleTable(["Bed", "Crop", "Area (acres)", "Yield (lbs)", "Status"],
        d.plots.map(p => [esc(p.id), esc(p.crop), fmt(p.acres), p.yield_bu > 0 ? fmt(p.yield_bu) : "—",
          `<span class="status-pill pill-${p.status}">${statusLabel[p.status] || p.status}</span>`]));
    case "sustainability":
      return simpleTable(["Month", "Carbon (kg CO₂)", "Water (gal)", "Solar (kWh)"],
        d.sustainability.map(r => [d.months[r.month-1], fmt(r.carbon_kg), fmt(r.water_gal), fmt(r.solar_kwh)]));
    case "inputs":
      return simpleTable(["Nutrient / Input", "Applied (ppm)", "Benchmark (ppm)"],
        d.inputs.map(i => [esc(i.name), fmt(i.applied), fmt(i.benchmark)]));
    case "economics":
      return simpleTable(["Crop", "Cost ($)", "Revenue ($)", "Profit ($)", "Margin (%)", "Per unit"],
        d.economics.map(e => { const p = e.revenue - e.cost, m = e.revenue ? Math.round(p/e.revenue*100) : 0;
          return [esc(e.crop), "$"+fmt(e.cost), "$"+fmt(e.revenue), "$"+fmt(p), m+"%", esc(e.unit)]; }));
    case "budget":
      return simpleTable(["Category", "Allocated ($)", "Spent ($)", "Remaining ($)", "Used (%)"],
        d.budget.map(b => { const rem = b.allocated - b.spent, pct = b.allocated ? Math.round(b.spent/b.allocated*100) : 0;
          return [esc(b.category), "$"+fmt(b.allocated), "$"+fmt(b.spent), "$"+fmt(rem), pct+"%"]; }));
    case "settings":
      return simpleTable(["Metric", "Value"], [
        ["Soil moisture (% VWC)", fmt(d.kpis.soil_moisture)],
        ["Soil health (index /10)", fmt(d.kpis.soil_health)],
        ["Grant total ($)", "$"+fmt(d.kpis.grant_total)],
      ]);
    case "milestones":
      return simpleTable(["#", "Milestone", "Date", "State"],
        d.milestones.map(m => [m.id, esc(m.label), esc(m.date), esc(m.state)]));
    case "tasks":
      return simpleTable(["Task", "Assignee", "Due", "Priority", "Status"],
        d.tasks.map(t => [esc(t.title), esc(t.assignee)||"—", esc(t.due)||"—",
          `<span class="prio-pill prio-${t.priority}">${t.priority}</span>`,
          `<span class="status-pill pill-${t.status}">${taskStatusLabel[t.status]||t.status}</span>`]));
    case "deadlines":
      return simpleTable(["Due", "Item", "Grant / Fund"],
        d.deadlines.map(dl => [esc(dl.due), esc(dl.item), esc(dl.grant)]));
    case "roadmap":
      return simpleTable(["Phase", "Item", "Detail", "Target", "Category", "Status"],
        (d.roadmap||[]).map(r => [esc(r.phase), esc(r.item), esc(r.detail), esc(r.due),
          `<span class="cat-tag cat-${esc(r.category)}">${esc(r.category)}</span>`,
          `<span class="status-pill pill-${r.status}">${r.status}</span>`]));
    case "csa": {
      const kind = d.catalog[wid].kind, s = d.csa.summary;
      if (kind === "csa_orders_table") {
        return simpleTable(["Date", "Customer", "Email", "Phone", "Location", "Zone", "Order", "Units", "Est. $"],
          d.csa.orders.map(o => {
            const units = Object.values(o.items_map || {}).reduce((a, b) => a + (b || 0), 0);
            const rev = Object.entries(o.items_map || {}).reduce((a, [k, v]) => a + (v || 0) * (d.csa.prices[k] || 0), 0);
            return [fmtDate(o.order_date), esc(o.customer), esc(o.email) || "—", esc(o.phone) || "—",
              esc(shortLoc(o.location)), esc(o.zone) || "—", esc(itemsSummary(o)), units, "$" + fmt(rev)];
          }));
      }
      if (kind === "csa_shares_pie") {
        const iu = s.item_units;
        return simpleTable(["Item", "Units sold", "Unit price ($)", "Est. revenue ($)"],
          Object.keys(iu).sort((a, b) => iu[b] - iu[a]).map(k =>
            [esc(k), fmt(iu[k]), "$" + fmt(d.csa.prices[k] || 0), "$" + fmt(iu[k] * (d.csa.prices[k] || 0))]));
      }
      // KPIs / orders-line / monthly-sales → the monthly analytics table
      return simpleTable(["Month", "Orders", "Units", "Est. sales ($)"],
        s.monthly.map(m => [monthLabel(m.month), m.orders, m.units, "$" + fmt(m.revenue)]));
    }
    case "framework": {
      const e = d.embodiment || {};
      if (d.catalog[wid].kind === "perfections")
        return simpleTable(["Perfection", "In the field", "What it trains"],
          (e.perfections||[]).map(x => [`<strong>${esc(x.name)}</strong>`, esc(x.field), esc(x.trains)]));
      if (d.catalog[wid].kind === "curriculum")
        return simpleTable(["Wk", "Phase", "Anchor", "Farm task", "Reflection prompt"],
          (e.curriculum||[]).map(x => [x.week, esc(x.phase), esc(x.anchor), esc(x.task), esc(x.prompt)]));
      return simpleTable(["Foundation", "Practice", "Meaning", "Embodied"],
        (e.foundations||[]).map(x => [`<strong>${esc(x.name)}</strong>`, esc(x.practice), esc(x.meaning), esc(x.embodied)]));
    }
    default:
      return `<div style="color:var(--muted);font-size:13px">No tabular data for this widget.</div>`;
  }
}

// Link to where the data originated: a connected Google Sheet, the framework
// document, or the Manage Data editor.
function sourceLink(wid, d) {
  const src = d.catalog[wid].source;
  const label = (d.embodiment && d.embodiment.source_labels && d.embodiment.source_labels[src]) || src;
  if (src === "framework") {
    return `<a class="src-btn" href="resources/purpose-driven-farming-framework.pdf" target="_blank" rel="noopener">
      📄 Open the ${esc(label)} (PDF) ↗</a>`;
  }
  if (src === "csa") {
    return `<a class="src-btn" href="resources/Farmhand_CSA_orders.xlsx" target="_blank" rel="noopener">
      📊 Open the ${esc(label)} ↗</a>
      <span class="src-sub">Revenue is estimated from editable unit prices —
      <a href="admin.html" target="_blank" rel="noopener">adjust prices in Manage Data</a>.</span>`;
  }
  if (SYNCABLE.has(src)) {
    const sheet = (d.sheets || []).find(s => s.target === src);
    if (sheet && sheet.sheet_url) {
      return `<a class="src-btn" href="${esc(sheet.sheet_url)}" target="_blank" rel="noopener">
        📊 Open source Google Sheet — ${esc(label)} ↗</a>
        <span class="src-sub">${sheet.last_status ? esc(sheet.last_status) + (sheet.last_sync ? " · " + new Date(sheet.last_sync).toLocaleString() : "") : "not yet synced"}</span>`;
    }
    return `<div class="src-none">No Google Sheet / Excel connected for <strong>${esc(label)}</strong> yet.
      <button class="src-btn ghost" onclick="closeModal('detail-modal'); renderSheets(); openModal('sheets-modal');">🔗 Connect a sheet</button>
      <a class="src-btn ghost" href="admin.html" target="_blank" rel="noopener">⚙ Edit in Manage Data ↗</a></div>`;
  }
  // Non-syncable datasets are edited directly on the Manage Data page.
  return `<a class="src-btn" href="admin.html" target="_blank" rel="noopener">⚙ Open source — ${esc(label)} ↗</a>`;
}

function openDetail(wid) {
  const d = DATA;
  const meta = d.catalog[wid];
  if (!meta) return;
  const cat = d.categories.find(c => c.id === meta.category);
  const hasChart = !!MOUNTERS[meta.kind];

  document.getElementById("detail-title").textContent = meta.title;
  const visual = hasChart
    ? `<div class="detail-visual"><canvas id="dcv-${wid}" height="240"></canvas></div>` : "";

  document.getElementById("detail-body").innerHTML = `
    ${cat && cat.principle ? `<div class="detail-principle"><span class="dp-cat">${cat.icon} ${esc(cat.label)}</span> ${esc(cat.principle)}</div>` : ""}
    ${visual}
    <h4 class="detail-h">Full data</h4>
    ${detailTable(wid, d)}
    <h4 class="detail-h">Source data</h4>
    <div class="detail-source">${sourceLink(wid, d)}</div>
    ${meta.human ? `<div class="detail-human">🌱 ${esc(meta.human)}</div>` : ""}`;

  openModal("detail-modal");

  // Mount the enlarged chart into the modal canvas (separate from the grid).
  if (hasChart) {
    CANVAS_PREFIX = "dcv-";
    try { MOUNTERS[meta.kind](d, wid); } finally { CANVAS_PREFIX = "cv-"; }
  }
}

function closeDetail() {
  Object.keys(detailCharts).forEach(k => { detailCharts[k].destroy(); delete detailCharts[k]; });
  closeModal("detail-modal");
}

/* ── Add-widget modal ───────────────────────────────── */
function renderCatalog() {
  const d = DATA;
  const inUse = new Set(d.widgets.filter(w => w.visible).map(w => w.wid));
  const byCat = {};
  Object.entries(d.catalog).forEach(([wid, meta]) => {
    (byCat[meta.category] = byCat[meta.category] || []).push([wid, meta]);
  });
  document.getElementById("catalog-list").innerHTML = d.categories.map(cat => {
    const list = byCat[cat.id] || [];
    if (!list.length) return "";
    return `<div class="catalog-group"><h4>${cat.icon} ${cat.label}</h4>
      ${list.map(([wid, meta]) => {
        const used = inUse.has(wid);
        return `<div class="catalog-item ${used ? "in-use" : ""}">
          <span class="ci-title">${esc(meta.title)}</span>
          <button ${used ? "disabled" : ""} onclick="addWidget('${wid}')">${used ? "In use" : "Add"}</button>
        </div>`;
      }).join("")}</div>`;
  }).join("");
}

/* ── Google Sheets modal ────────────────────────────── */
const SHEET_FIELDS = {
  plots: "id, crop, acres, yield_bu, status, x_pct, y_pct",
  budget: "category, allocated, spent",
  monthly_yield: "month, crop, bushels",
  inputs: "name, applied, benchmark",
  community: "month, lbs_dist, families, volunteer_hrs, csa_shares",
  sustainability: "month, carbon_kg, water_gal, solar_kwh",
  economics: "crop, cost, revenue, unit",
};
function renderSheets() {
  document.getElementById("sheets-list").innerHTML = DATA.sheets.map(s => `
    <div class="sheet-row">
      <div class="sr-top">
        <span class="sr-name">${s.target.replace("_", " ")}</span>
        <label class="switch"><input type="checkbox" data-en="${s.target}" ${s.enabled ? "checked" : ""}> weekly auto-sync</label>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:5px">Columns: ${SHEET_FIELDS[s.target] || ""}</div>
      <input type="text" data-url="${s.target}" placeholder="https://docs.google.com/spreadsheets/d/.../edit#gid=0"
        value="${esc(s.sheet_url)}">
      <div class="sr-actions">
        <span class="sr-status">${s.last_status ? esc(s.last_status) + (s.last_sync ? " · " + new Date(s.last_sync).toLocaleString() : "") : "Not yet synced"}</span>
        <button class="btn-ghost" onclick="saveSheet('${s.target}')">Save</button>
        <button class="btn-primary" onclick="syncSheet('${s.target}')">Sync now</button>
      </div>
    </div>`).join("");
}
async function saveSheet(target) {
  const url = document.querySelector(`[data-url="${target}"]`).value.trim();
  const enabled = document.querySelector(`[data-en="${target}"]`).checked ? 1 : 0;
  try {
    await api("PUT", `/api/sheets/${target}`, { sheet_url: url, enabled });
    toast(`Saved ${target} connection`);
    await refresh(true); renderSheets();
  } catch (e) { toast(e.message, true); }
}
async function syncSheet(target) {
  await saveSheet(target);
  try {
    const r = await api("POST", "/api/sheets/sync", { target });
    toast(r.message, !r.ok);
    await refresh(true); renderSheets();
  } catch (e) { toast(e.message, true); }
}

/* ── Modals ─────────────────────────────────────────── */
function openModal(id) { document.getElementById(id).classList.add("show"); }
function closeModal(id) { document.getElementById(id).classList.remove("show"); }

/* ── Filters / density wiring ───────────────────────── */
function wireControls() {
  document.getElementById("filter-crop").addEventListener("change", e => { filters.crop = e.target.value; renderGrid(); });
  document.getElementById("filter-status").addEventListener("change", e => { filters.status = e.target.value; renderGrid(); });
  document.getElementById("open-add").addEventListener("click", () => { renderCatalog(); openModal("add-modal"); });
  document.getElementById("open-sheets").addEventListener("click", () => { renderSheets(); openModal("sheets-modal"); });
  document.getElementById("restore-all").addEventListener("click", restoreAll);
  document.getElementById("menu-toggle").addEventListener("click", () =>
    document.getElementById("sidebar").classList.toggle("open"));

  const setDensity = mode => {
    density = mode;
    document.getElementById("dens-all").classList.toggle("on", mode === "all");
    document.getElementById("dens-focus").classList.toggle("on", mode === "focus");
    document.getElementById("density-note").textContent =
      mode === "focus" ? "Focused view — headline widgets only" : "";
    renderGrid();
  };
  document.getElementById("dens-all").addEventListener("click", () => setDensity("all"));
  document.getElementById("dens-focus").addEventListener("click", () => setDensity("focus"));

  // Close modals on backdrop click (detail modal also tears down its charts)
  document.querySelectorAll(".modal-bg").forEach(bg =>
    bg.addEventListener("click", e => {
      if (e.target !== bg) return;
      if (bg.id === "detail-modal") closeDetail(); else bg.classList.remove("show");
    }));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (document.getElementById("detail-modal").classList.contains("show")) closeDetail();
      document.querySelectorAll(".modal-bg.show").forEach(bg => bg.classList.remove("show"));
    }
  });

  if (window.innerWidth <= 720) document.getElementById("menu-toggle").style.display = "inline-block";
}

function refreshCropFilter() {
  const sel = document.getElementById("filter-crop");
  const crops = [...new Set(DATA.plots.map(p => p.crop))].sort();
  const cur = sel.value;
  sel.innerHTML = `<option value="">All Crops</option>` + crops.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  sel.value = crops.includes(cur) ? cur : "";
}

/* ── Polling ────────────────────────────────────────── */
const badge = document.getElementById("live-badge");
async function refresh(force = false) {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) throw new Error(res.status);
    const text = await res.text();
    badge.textContent = "⟳ Live"; badge.classList.remove("offline");
    if (text !== lastPayload || force) {
      lastPayload = text;
      DATA = JSON.parse(text);
      refreshCropFilter();
      renderSidebar();
      renderGrid();
      document.getElementById("last-sync").textContent =
        new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
    }
  } catch (e) {
    badge.textContent = "⚠ API offline"; badge.classList.add("offline");
  }
}

/* ── Boot ───────────────────────────────────────────── */
(async function init() {
  wireControls();
  await refresh(true);
  if (DATA) selectCategory("all");   // surface the guiding tagline on load
  setInterval(refresh, 4000);
})();
