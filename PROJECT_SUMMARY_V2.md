# Urban GreenWorks Almanac — Project Summary & V2 Roadmap

**Madeline Maynard — MBA 631, Analytics Project Implementation**
**Cerasee Farm & Urban GreenWorks (Liberty City, Miami)**

---

## 1. Overview

The V2 proposal envisioned an interactive dashboard to surface Urban GreenWorks &
Cerasee Farm's metrics — community benefit, crop yields, and sustainability — pulled
from the farm's own working spreadsheets, to help secure funding, support carbon-credit
records, and ultimately let the farm model be replicated in other urban food deserts.

That vision is now a **working, data-driven application**, not just a mockup. The
**Urban GreenWorks Almanac** is a live dashboard built on the farm's real records, with
an admin backend for staff to maintain the data themselves, a built-in AI assistant, and
live Miami weather. The original plan named Tableau for visualization; the build went a
step further into a **custom, self-hosted web app** so the farm owns the whole stack —
no licensing cost, no per-seat fee, and full control over how data is entered and shown.

---

## 2. What We've Accomplished (V1 — built and live)

Mapped against the proposal's goals:

| Proposal goal | Status | What exists today |
|---|---|---|
| Interactive dashboard of farm metrics | ✅ Done | Widget-driven dashboard: drag-to-arrange, minimize, maximize, filter by category |
| Crop yields | ✅ Done | Real harvest data for the top 12 crops (Papaya, Collard, Mango, Cucumber, Bell Pepper, Cabbage, Pak Choi, Carrot, Pumpkin, Lettuce, Eggplant, Fennel), with monthly seasonality |
| Pull from farm spreadsheets | ✅ Done | Excel/CSV upload + Google Sheets weekly sync — staff update data without touching code |
| Soil / nutrient makeup | ✅ Done | Soil composition tracking (heavy-metal panel, lead, pH by garden) from three lab/university reports, with safe-limit flags |
| Sustainability data | ✅ Partial | Sustainability metrics table + widgets in place; carbon, solar, and water are scaffolded for V2 (see §4) |
| Weather conditions vs. harvest | ✅ Done | **Live** Miami climate (Open-Meteo) overlaid on harvest, plus active watch/warning alerts from the National Weather Service (hurricane, flood, drought, heat, frost) |
| Library of nutritional / herbal benefits | ✅ Done | Per-crop "deep dive" on maximize: yield over time + nutritional, cultural, and herbal value |
| Community benefit, quantified | ✅ Done | Community impact widgets (people served, volunteer hours, food access) |
| Project manager (tasks, deadlines, budget) | ✅ Done | Tasks & deadlines, grant milestones, and budget widgets |
| AI integration | ✅ Done | **Cerasee** — an in-dashboard AI assistant (Anthropic) that answers questions about the live data; staff add their own API key in the backend |
| Editable backend for non-technical staff | ✅ Done | Admin page auto-generates an editor for every data table; widget titles/units editable; data roadmap editable |
| Foundation for replication | ✅ Done | Generic table-registry architecture (see §6) makes the whole app reconfigurable for another farm |

**Beyond the proposal**, V1 also delivered:
- A **self-healing layout** that restores default widgets if any are lost.
- A **Data Roadmap** panel built into the sidebar — the farm's own editable wishlist of
  future data to integrate (this doubles as the V2 backlog below).
- **Zero-dependency hosting** (Python standard library + SQLite) — it runs by
  double-clicking one launcher; nothing to install or pay for.
- Earth-tone, category-coded design and proper units on every metric.

---

## 3. Data Assets Currently in the Dashboard

These tables are live and feeding widgets today:

- **Crops** & **crop yield** — species, real harvest weights, monthly yield series
- **Beds** — garden beds mapped to the crops planted in them
- **Crop log** & **harvest trend** — seedlings planted / harvested, germination, monthly totals (2023–2025)
- **Soil tests** — heavy-metal + lead + pH results by garden, with safe-limit flags
- **Sustainability** — sustainability metrics
- **Community** — community-impact figures
- **Tasks**, **milestones**, **budget** — operations & grant management
- **Inputs** — growing inputs (seed source, compost, etc.)
- **Weather** & **weather alerts** — live Miami climate + NWS alerts
- **Partners** — community partners
- **Settings**, **widgets**, **sheets** — app configuration, layout, and sync sources

---

## 4. What Still Can Be Done (V2 Roadmap)

These are the future data assets to integrate — already listed (and editable) in the
dashboard's own roadmap panel, so the farm can re-prioritize them over time:

| Asset | Category | Why it matters |
|---|---|---|
| **Carbon soil testing** | Sustainability | Lab CO₂ / organic-matter panels to **quantify sequestration for carbon-credit programs** — a direct revenue/funding lever named in the proposal |
| **Solar output** | Sustainability | Daily kWh from the rooftop array (live meter feed or monthly bill import) |
| **Water usage** | Sustainability | Irrigation draw + rainwater capture, broken out by bed or zone |
| **CSA impacts** | Community Impact | Track CSA shares, member retention, and food-access outcomes |
| **CSA order hub** | Community Impact | Bring the **currently-outsourced** CSA ordering in-house: orders, pickups, payments |
| **Calendar of events** | Operations | Workshops, volunteer days, market dates, planned harvest windows |
| **Organic certification progress** | Certification | Checklist + milestones toward USDA Organic / regenerative certification |
| **Comb Cutters hive data** | Partners | Honey yield + pollination metrics from the on-site beekeeping partner |
| **Growing-degree days** | Crops & Yield | Correlate logged conditions with harvest to refine planting and **increase yield** |
| **AI growing-map generator** | Crops & Yield | Generate a planting map from bed sizes + planned crops (a stretch goal from the proposal) |
| **Per-crop cost & profit margins** | Operations | Combine inputs + yield + price to compute margin per crop |

Each of these plugs into the existing architecture with no redesign — a new table entry
in the registry plus a widget definition.

---

## 5. A Mobile / Web App for the Dashboard

Today the Almanac is a web app run on a computer. The natural V2 step is to make it
**accessible anywhere**, which matters for staff and volunteers logging data **in the
field**:

- **Hosted version** — deploy to a small cloud host so the dashboard lives at a URL the
  whole team can open from any device, instead of one machine.
- **Mobile-friendly entry** — a phone-optimized data-entry view so volunteers log
  harvests, tasks, and observations at the bed instead of on paper, then later at a desk.
- **Installable app (PWA)** — package the existing web app as a "progressive web app"
  staff can add to a phone home screen. This reuses everything already built — no separate
  iOS/Android codebase — making it the lowest-cost path to an "app."
- **Roles & logins** — basic accounts (admin vs. volunteer) once it's multi-user, so the
  ED controls who can edit what.

---

## 6. Scaling for Use by Other Farms

The proposal's biggest ambition — letting the farm model be **replicated in other urban
food deserts and growing zones** — is structurally supported by how V1 was built:

- **Configurable by design.** The entire app is driven by a generic table registry and a
  widget catalog. A new farm gets its own data and its own dashboard by editing
  configuration — not by rewriting code.
- **Growing-zone aware.** Weather is already pulled live by latitude/longitude, so a farm
  in a different climate zone gets its own local weather and harvest comparison
  automatically.
- **Template + clone model (V2).** Package the Almanac as a **starter template**: a new
  farm clones it, clears the sample data, runs the admin importer on their own
  spreadsheets, and is live. This turns the project into a reusable toolkit for the urban
  agriculture network rather than a one-farm tool.
- **Shared benchmarking (longer term).** With several farms on the same platform,
  aggregate (anonymized) metrics could let farms compare yields, soil health, and
  community impact across regions — strengthening **collective grant applications and
  carbon-credit programs**.

---

## 7. Summary

V1 delivered a working, real-data dashboard that already covers crop yields, soil health,
community impact, operations/grant management, live weather, and an AI assistant — with a
non-technical backend so the farm can maintain it independently. The remaining work is
**additive, not corrective**: layering in sustainability data that drives funding
(carbon, solar, water), bringing the CSA in-house, making it mobile-accessible, and
packaging it so other farms can adopt it. The architecture was deliberately built to make
each of those a configuration step rather than a rebuild.
