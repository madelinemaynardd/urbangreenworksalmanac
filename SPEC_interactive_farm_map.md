# Implementation Spec — Interactive, Editable Farm Map

**Project:** Urban GreenWorks Almanac (Cerasee Farm)
**Feature area:** Growing Map widget (`map` widget type)
**Status:** Spec / not yet built
**Author context:** Extends the existing `beds` table + `mapHtml()` renderer

---

## 1. Goal

Turn the current decorative map into a **real, editable, to-scale plan of the farm**, where:

1. The user draws/edits the map to match the **real layout and square footage**.
2. Each **growing section** is customizable by growing method (in-ground, raised bed, high tunnel, container, vertical, greenhouse).
3. Each section can **toggle irrigation on/off** and record the **irrigation type** (drip, sprinkler, soaker, hand-water, none).
4. **Clicking a section's crop** opens the crop detail we already store (yield-over-time, nutrition, culture, herbal) **plus new seed-to-harvest timing** and **where in the growing cycle** that crop currently is.
5. Reserve structured, empty fields now so a later data drop can populate **profit margin per crop, seed-to-sale**, with no schema rework.

### What exists today (baseline)
- `beds` table: `id, name, crop_id, size_sqft, status, x_pct, y_pct` — a **single point** (`x_pct`/`y_pct`) with no width/height/shape. server.py:70
- `mapHtml()` renders each bed as a **positioned dot** on a CSS gradient background; there is no scale, no editing, no click-through. index.html:753
- Crop detail already exists via `renderCropDetail()` (yield chart + nutrition/culture/herbal/economics panels). index.html:867
- Everything is driven by the `TABLES` registry + generic CRUD, and the admin page auto-generates an editor per table. This spec **extends the registry**, consistent with the architecture.

---

## 2. Data model changes

### 2.1 Extend the `beds` table (rename concept → "growing sections")

Keep the table name `beds` (avoids migration churn) but treat each row as a **growing section / plot**. Add columns to `TABLES["beds"]["cols"]` in server.py:

| Column | Type | Purpose |
|---|---|---|
| `x_pct` | float | left edge, % of plot width *(existing — repurposed from point to rect origin)* |
| `y_pct` | float | top edge, % of plot height *(existing)* |
| `w_pct` | float | **new** — width, % of plot width |
| `h_pct` | float | **new** — height, % of plot height |
| `shape` | str | **new** — `rect` \| `circle` (default `rect`) |
| `grow_type` | str | **new** — `in_ground` \| `raised_bed` \| `high_tunnel` \| `container` \| `vertical` \| `greenhouse` |
| `irrigated` | int | **new** — 0/1 toggle |
| `irrigation_type` | str | **new** — `drip` \| `sprinkler` \| `soaker` \| `hand` \| `none` |
| `planted_date` | str | **new** — ISO date the current crop went in (drives cycle stage) |
| `notes` | str | **new** — free text |

`size_sqft` stays and becomes **derived-or-entered**: when the user resizes a section, auto-fill `size_sqft` from the farm's real total (see §2.2) but let them override.

### 2.2 New `farm_plot` settings (one row)

Add a tiny singleton table (or reuse `settings`) to store the **canvas → real-world scale** so square footage is truthful:

| Key | Example | Purpose |
|---|---|---|
| `plot_width_ft` | 120 | real width of the mapped area |
| `plot_length_ft` | 80 | real length |
| `plot_name` | "Main lot — 71st St" | label |

Total sqft = `plot_width_ft * plot_length_ft`. A section's sqft = `w_pct/100 * h_pct/100 * total_sqft` (auto-suggested; user can override for irregular beds). This is what makes the map **based on real square footage** rather than arbitrary pixels.

### 2.3 Crop cycle timing (extend `crops`)

Add to `TABLES["crops"]["cols"]` so "seed-to-harvest rate" and "where in the cycle" are data, not guesses:

| Column | Type | Purpose |
|---|---|---|
| `days_to_harvest` | int | seed→first harvest (from your logs / seed packets) |
| `harvest_window_days` | int | how long it keeps producing |
| `germ_days` | int | seed→germination (you already track germ %) |

If you'd rather not touch `crops`, these can live in the existing `crop_log` table instead (it's already per-crop). Recommend `crops` since the detail panel reads from `crops`.

### 2.4 Profit-margin placeholders (seed-to-sale) — reserve now, fill later

You already have `crops.cost` and `crops.price`. Add the missing seed-to-sale cost components so the later data drop lands cleanly:

| Column | Type | Meaning |
|---|---|---|
| `seed_cost` | float | seed/start cost per unit or per bed |
| `labor_cost` | float | labor allocated per lb |
| `input_cost` | float | compost/water/amendments per lb |
| `sale_price` | float | actual realized sale price (vs. `price` = list) |
| `margin_note` | str | free text until real numbers arrive |

**Derived margin** (computed in UI, not stored): `margin = sale_price − (seed_cost + labor_cost + input_cost + cost)`. Until you supply data, these are `0`/blank and the panel shows "Awaiting cost data" — no rework when numbers come in.

---

## 3. Frontend — map rendering (view mode)

Replace `mapHtml()` (index.html:753) so each bed renders as a **scaled rectangle/circle**, not a dot:

- Container keeps aspect ratio of `plot_width_ft : plot_length_ft` so the drawing is proportional to the real lot.
- Each section is an absolutely-positioned box at `left:x_pct% top:y_pct% width:w_pct% height:h_pct%`.
- **Fill color = crop category / status**; reuse existing status colors (On Track / At Risk / Delayed / Complete).
- **Icon badges** in each box: a small glyph for `grow_type` (e.g. 🌱 in-ground, 🟫 raised bed, ⛺ high tunnel, 🪴 container, 🧱 vertical, 🏠 greenhouse) and a 💧 badge when `irrigated=1` (tooltip shows `irrigation_type`).
- **Label**: crop name + size (`"Collards · 40 sqft"`).
- Legend expands to show grow-type glyphs and the irrigation badge.
- **Hover** → tooltip with crop, grow type, irrigation, sqft, planted date, cycle stage.
- **Click a section** → `openCropDetail(crop_id, widgetId)` (already wired) → opens the maximize panel on that crop.

Add a small **"Edit map"** button in the widget header (only this widget) that flips into edit mode (§4).

---

## 4. Frontend — map editor (edit mode)

A lightweight, dependency-free editor (no new libraries — the project is intentionally zero-dependency; use pointer events + inline SVG/DIVs).

**Canvas interactions**
- **Add section:** click empty space → creates a default rect (10%×10%) → opens the section inspector.
- **Move:** drag a section; snaps to a light grid (e.g. 2%).
- **Resize:** drag a corner handle; live-updates `w_pct/h_pct` and the auto-computed sqft readout.
- **Select:** click a section → **inspector panel** on the right.

**Inspector panel fields** (write back to the `beds` row via existing `PUT /api/data/beds/<id>`):
- Name (text)
- Crop (dropdown from `crops`)
- Growing type (dropdown: in-ground / raised bed / high tunnel / container / vertical / greenhouse)
- Irrigation: **toggle**; if on → type dropdown (drip / sprinkler / soaker / hand)
- Size sqft (auto-filled from scale, editable)
- Planted date (date picker)
- Status (existing)
- Notes
- **Delete section** button

**Scale controls** (top of editor): plot width_ft / length_ft inputs → persist to §2.2, live-relabel all sqft.

**Save model:** each field change does an optimistic `PUT` (consistent with how the rest of the admin saves). No separate "save" needed, but include a "Done editing" button that exits edit mode and re-renders view.

> Persistence uses the **existing generic CRUD** — no new endpoints required for bed edits. Only the scale singleton (§2.2) may need a `settings` read/write, which already exists.

---

## 5. Crop detail additions (click-through)

Extend `renderCropDetail()` (index.html:867) with two panels, appended to the existing nutrition/culture/herbal/economics set:

### 5.1 "Growing Cycle" panel
- **Seed-to-harvest**: show `germ_days`, `days_to_harvest`, `harvest_window_days`.
- **Where in the cycle now**: compute from the section's `planted_date`:
  `elapsed = today − planted_date` →
  - `elapsed < germ_days` → **Germinating**
  - `< days_to_harvest` → **Growing** (progress bar `elapsed / days_to_harvest`)
  - `< days_to_harvest + harvest_window_days` → **Harvesting**
  - else → **Past window / replant**
- Render as a horizontal **stage bar** (Seeded → Germinated → Growing → Harvest) with a marker at the current position. Reuses existing progress-bar styling.
- If a crop is planted in multiple sections with different dates, show one row per section.

### 5.2 "Profit Margin (seed-to-sale)" panel — placeholder-aware
- Grid of: seed cost, input cost, labor cost, total cost/lb, sale price/lb, **margin/lb**, and **margin %**.
- When the underlying fields are all 0/blank → render a muted **"Awaiting seed-to-sale cost data"** state instead of fake numbers.
- When you later supply data, this panel populates automatically — no code change, since it reads the reserved columns from §2.4.

---

## 6. Admin page

The generic auto-editor already exposes new `beds`/`crops` columns for free (that's the point of the registry). Add on top:

- A friendly **grow-type** and **irrigation-type** dropdown in the beds editor (mirror how `weather_alerts` uses select fields).
- The **scale** inputs (`plot_width_ft`, `plot_length_ft`) surfaced in the "Growing Map" area or Integrations tab.
- Everything else (adding a crop's `days_to_harvest`, cost fields) works through the existing table editor immediately.

---

## 7. Build order (incremental, each shippable)

1. **Schema**: add columns to `beds` + `crops`, add scale settings, extend seeds with sensible defaults (convert existing point beds → small rects). Ship — nothing breaks; map still renders.
2. **Scaled view render**: rewrite `mapHtml()` to draw boxes to scale with grow-type/irrigation badges + click-through. Ship.
3. **Editor mode**: add/move/resize/inspector with optimistic PUTs + scale controls. Ship.
4. **Crop cycle panel**: `days_to_harvest` math + stage bar in `renderCropDetail()`. Ship.
5. **Profit-margin panel**: placeholder-aware seed-to-sale grid. Ship (shows "awaiting data" until you provide numbers).

---

## 8. Data you'll need to provide

To make this real (not sample), collect:
- **Plot dimensions** (width × length in feet) of the mapped area.
- **Per section**: name, which crop, grow type, irrigation (y/n + type), size (or let scale compute it), planting date.
- **Per crop**: germination days, days to harvest, harvest window (from seed packets / your logs).
- **Later**: seed cost, input cost, labor cost, actual sale price per crop → fills the margin panel.

---

## 9. Non-goals (this pass)
- Satellite/GPS imagery or lat-long geo-mapping (the % canvas + ft scale is enough and stays dependency-free).
- Multi-plot farms with separate lots (single mapped area for now; the scale singleton can later become per-plot rows to support §Scaling in the V2 roadmap).
- Real-time irrigation sensor feeds (that's a future roadmap item; this only records the *type* in use).
