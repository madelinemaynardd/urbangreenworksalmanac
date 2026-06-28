# 🌿 Urban GreenWorks Almanac

An interactive analytics dashboard for **Cerasee Farm & Urban GreenWorks** — a nonprofit
urban farm in Liberty City, Miami, rooted in Caribbean growing traditions and regenerative
agriculture. Built as the MBA 631 (Analytics Project Implementation) final project.

It turns the farm's real records — crop yields, seeding/harvest logs, soil tests, grant
budget, and community impact — into a live, widget-driven dashboard, with an AI assistant and
live Miami weather.

## Features

- **Widget dashboard** — drag-to-reorder, minimize-to-tray, maximize, add/remove widgets, and a
  left sidebar that filters by earth-tone-coded category.
- **Real farm data** — crops, monthly harvest, seedlings, and a per-crop deep dive
  (yield over time + nutritional / cultural / herbal value), aggregated from the UGW logs.
- **Soil composition tracking** — heavy-metal and pH results from three lab/university reports,
  with safe-limit flags.
- **Live Miami weather** — monthly rainfall/temperature from [Open-Meteo](https://open-meteo.com)
  overlaid on harvest, plus active watches/warnings from the U.S. National Weather Service.
- **Cerasee** — a built-in AI assistant (Anthropic API) that answers questions about the data.
- **Data roadmap** — an editable wishlist of future data assets to integrate.
- **Backend admin** — edit every table, upload Excel/CSV, and connect Google Sheets for weekly sync.

## Tech

Pure **Python standard library** (no pip installs) — an `http.server` backend over **SQLite**,
serving a vanilla HTML/CSS/JS frontend with [Chart.js](https://www.chartjs.org/) from a CDN.

## Run it

```bash
python server.py
```

Then open **http://localhost:7654** (admin at `/admin.html`).
On Windows you can also double-click **`Launch AgriGrant.bat`**.

The SQLite database (`agrigrant.db`) is created and seeded automatically on first run — it is
**not** checked in (it holds runtime data and the AI API key).

### Optional setup

- **AI assistant (Cerasee):** add your Anthropic API key under *Manage Data → Cerasee*.
- **Live weather:** syncs automatically on startup and daily; refresh on demand under *Manage Data → Weather*.
- **Google Sheets sync:** publish a sheet as CSV and paste the link under *Manage Data → Integrations*.
