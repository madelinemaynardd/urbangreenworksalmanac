#!/usr/bin/env python3
"""AgriGrant Dashboard backend — Cerasee Farm & Urban GreenWorks.

Serves the static frontend and a JSON REST API backed by SQLite.
Run: python3 server.py   (listens on http://localhost:7654)

This backend powers a category-organized, widget-based dashboard:
  • Community Impact   produce distributed, families served, volunteer hours, CSA
  • Crop Yields        yields by bed/crop and monthly progress
  • Sustainability     carbon, soil nutrients, water, solar
  • Crop Economics     cost & profit margin per crop
  • Grants & Budget    grant utilization, budget by category
  • Project Mgmt       tasks / to-dos / deadlines for staff & volunteers
  • Field Map          bed layout

Widgets are first-class records (add / delete / minimize / reorder), and a
Google Sheets connector can refresh any data table on a weekly schedule.

See API map in the route table at the bottom of each do_* handler.
"""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import csv
import io
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "agrigrant.db")
PORT = 7654

PLOT_STATUSES = {"on-track", "at-risk", "delayed", "complete", "pending"}
MILESTONE_STATES = {"done", "active", "pending"}
TASK_STATUSES = {"todo", "in-progress", "blocked", "done"}
TASK_PRIORITIES = {"low", "medium", "high"}
ROADMAP_STATUSES = {"todo", "in-progress", "done"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Widget catalog — every chart/table the frontend knows how to render.
# category is used by the sidebar filter; "kind" maps to a renderer in app.js.
# "source" names the dataset a widget draws from — used to link the widget to
# the Google Sheet / Excel it originated from when the widget is expanded.
# "human" is the embodied-design anchor: a one-line reminder that the number
# stands for people, labor, and living soil — never data for its own sake.
WIDGET_CATALOG = {
    # Community Impact
    "community_kpis":   {"title": "Community Impact (KPIs)",          "category": "community",      "kind": "community_kpis",  "span": 4, "source": "community",      "human": "Every pound here is a meal on a Liberty City table — generosity made countable, not the point of the work."},
    "produce_dist":     {"title": "Produce Distributed by Month",     "category": "community",      "kind": "line_produce",    "span": 2, "source": "community",      "human": "A rising line is hands harvesting, sorting, and carrying food to neighbors who needed it."},
    "csa_shares":       {"title": "CSA Shares & Families Served",     "category": "community",      "kind": "community_table", "span": 2, "source": "community",      "human": "Each share is a household in relationship with this farm, not a transaction."},
    # Crop Yields
    "yield_line":       {"title": "Monthly Yield Progress",           "category": "yields",         "kind": "yield_line",      "span": 2, "source": "monthly_yield",  "human": "Yield is the visible end of patience — soil worked season after season until it answers."},
    "crop_pie":         {"title": "Crop Distribution by Bed Area",    "category": "yields",         "kind": "crop_pie",        "span": 2, "source": "plots",          "human": "How the land is shared among crops reflects choices made by the growers who tend each bed."},
    "plot_table":       {"title": "Bed / Plot Status Summary",        "category": "yields",         "kind": "plot_table",      "span": 2, "source": "plots",          "human": "Behind every 'on-track' bed is someone who showed up to weed, water, and watch it."},
    "yield_kpi":        {"title": "Total Yield (YTD)",                "category": "yields",         "kind": "kpi_yield",       "span": 1, "source": "plots",          "human": "One number for a year of effort, weather, and restraint."},
    # Sustainability
    "carbon_kpi":       {"title": "Carbon Sequestered (YTD)",         "category": "sustainability", "kind": "kpi_carbon",      "span": 1, "source": "sustainability", "human": "Carbon held in living soil — wisdom the ground keeps that no certificate can replace."},
    "water_kpi":        {"title": "Water Used (YTD)",                 "category": "sustainability", "kind": "kpi_water",       "span": 1, "source": "sustainability", "human": "Water is borrowed, not owned — restraint measured in gallons."},
    "solar_kpi":        {"title": "Solar Generated (YTD)",            "category": "sustainability", "kind": "kpi_solar",       "span": 1, "source": "sustainability", "human": "Energy the farm makes rather than takes."},
    "soil_moisture":    {"title": "Avg Soil Moisture",                "category": "sustainability", "kind": "moisture_gauge",  "span": 1, "source": "settings",       "human": "The body knows before the gauge does — a grower feels dry soil underfoot."},
    "sustainability_trend": {"title": "Sustainability Trends",        "category": "sustainability", "kind": "sustain_line",    "span": 2, "source": "sustainability", "human": "Regeneration doesn't respond to urgency; these lines move at the land's own pace."},
    "soil_nutrients":   {"title": "Soil Nutrient Makeup (NPK)",       "category": "sustainability", "kind": "inputs_chart",    "span": 2, "source": "inputs",         "human": "Hands in soil are a form of knowing that reading about soil cannot substitute for."},
    # Crop Economics
    "econ_table":       {"title": "Cost & Profit Margin by Crop",     "category": "economics",      "kind": "econ_table",      "span": 4, "source": "economics",      "human": "Pricing that doesn't extract maximum margin from a food-insecure neighborhood is a value, made visible here as a choice."},
    "margin_chart":     {"title": "Profit Margin by Crop",            "category": "economics",      "kind": "margin_chart",    "span": 2, "source": "economics",      "human": "Margin funds the mission; it is never the mission."},
    # Grants & Budget
    "grant_kpi":        {"title": "Grant Utilization",                "category": "grants",         "kind": "kpi_utilization", "span": 1, "source": "budget",         "human": "Truthfulness to funders: what was promised, what was spent, plainly."},
    "budget_chart":     {"title": "Budget Allocated vs. Spent",       "category": "grants",         "kind": "budget_chart",    "span": 2, "source": "budget",         "human": "Stewardship of trust others placed in this farm."},
    "budget_progress":  {"title": "Grant Budget Progress",            "category": "grants",         "kind": "budget_progress", "span": 1, "source": "budget",         "human": "Determination across a slow grant year, category by category."},
    "timeline":         {"title": "Project Milestones",               "category": "grants",         "kind": "timeline",        "span": 2, "source": "milestones",     "human": "Follow-through when the payoff is delayed."},
    # Project Management
    "task_board":       {"title": "Tasks & To-Dos",                   "category": "tasks",          "kind": "task_table",      "span": 4, "source": "tasks",          "human": "The unglamorous daily labor — weeding, watering, tending — that regeneration actually requires, and the people doing it."},
    "roadmap":          {"title": "Milestone Roadmap",                "category": "tasks",          "kind": "roadmap",         "span": 4, "source": "roadmap",        "human": "Determination and follow-through — the farm's commitments across the seasons ahead."},
    "deadlines":        {"title": "Upcoming Grant Deadlines",         "category": "tasks",          "kind": "deadline_list",   "span": 2, "source": "deadlines",      "human": "Commitments the farm keeps to the community that funds it."},
    # CSA Program
    "csa_kpis":         {"title": "CSA Program (KPIs)",               "category": "csa",            "kind": "csa_kpis",        "span": 4, "source": "csa",            "human": "Each order is a household choosing this farm week after week — relationship, not just revenue."},
    "csa_orders_line":  {"title": "CSA Orders Over Time",             "category": "csa",            "kind": "csa_orders_line", "span": 2, "source": "csa",            "human": "A season of pickups, deliveries, and the people who kept coming back."},
    "csa_shares_pie":   {"title": "Farm Share Popularity",           "category": "csa",            "kind": "csa_shares_pie",  "span": 2, "source": "csa",            "human": "What neighbors actually want on their tables."},
    "csa_monthly_sales":{"title": "CSA Sales by Month",              "category": "csa",            "kind": "csa_monthly_sales","span": 2, "source": "csa",           "human": "Income that keeps the fair-wage, chemical-free model viable."},
    "csa_orders_table": {"title": "CSA Order Breakdown",             "category": "csa",            "kind": "csa_orders_table","span": 4, "source": "csa",            "human": "Every order: who, when, where, and how much — the community made legible."},
    # Field Map
    "field_map":        {"title": "Field / Bed Map",                  "category": "map",            "kind": "field_map",       "span": 2, "source": "plots",          "human": "This is a place, not a grid — walked daily by the people who grow here."},
    # Purpose & Practice (embodiment layer)
    "guiding_foundations": {"title": "The Three Foundations",         "category": "purpose",        "kind": "foundations",     "span": 2, "source": "framework",      "human": "The ground everything above stands on: morality, mind-mastery, wisdom."},
    "ten_perfections":  {"title": "Ten Perfections in the Field",     "category": "purpose",        "kind": "perfections",     "span": 2, "source": "framework",      "human": "Values a farmer practices with their body until they become their own."},
    "agriworks_curriculum": {"title": "AgriWorks Curriculum (13 Weeks)", "category": "purpose",     "kind": "curriculum",      "span": 4, "source": "framework",      "human": "Practice comes first; the naming of the value comes after."},
    "field_reflection": {"title": "Field Reflection",                 "category": "purpose",        "kind": "reflection",      "span": 2, "source": "framework",      "human": "A question to carry into the beds today."},
}

CATEGORIES = [
    {"id": "purpose",       "label": "Purpose & Practice", "icon": "🌿",
     "principle": "Farming here is spiritual, physical, and sacred — food is grown as practice, not only product."},
    {"id": "community",      "label": "Community Impact",  "icon": "🤝",
     "principle": "Generosity — loosening the grip of ownership over what the land produces."},
    {"id": "csa",            "label": "CSA Program",       "icon": "🧺",
     "principle": "Loving-Kindness — a standing relationship with the households the farm feeds."},
    {"id": "yields",         "label": "Crop Yields",       "icon": "🌽",
     "principle": "Patience & Wisdom — soil verified by working it, season after season."},
    {"id": "sustainability", "label": "Sustainability",    "icon": "🌱",
     "principle": "Renunciation — restraint as strength: taking less than the land could give."},
    {"id": "economics",      "label": "Crop Economics",    "icon": "💵",
     "principle": "Morality — honest treatment of land, labor, and eaters alike."},
    {"id": "grants",         "label": "Grants & Budget",   "icon": "📋",
     "principle": "Truthfulness — alignment between what is practiced and what is claimed."},
    {"id": "tasks",          "label": "Project Mgmt",      "icon": "✅",
     "principle": "Effort — right-directed, sustained exertion, not sporadic bursts."},
    {"id": "map",            "label": "Field Map",         "icon": "🗺️",
     "principle": "Mind-Mastery — observe the site patiently before intervening."},
]

# ── Embodiment framework (Purpose Driven Farming) ────────────────────────────
# Static reference content served to the dashboard so the human, values-based
# dimension of the work is structural, not decorative. Drawn from the farm's
# "Purpose Driven Farming" synthesis (Three Foundations + Ten Perfections).
EMBODIMENT = {
    "tagline": "Where food is grown as practice, not just product.",
    "foundations": [
        {"name": "Morality",      "practice": "Organic practice",
         "meaning": "Refusing inputs and shortcuts that harm soil, workers, or eaters — even when conventional methods are faster or cheaper.",
         "embodied": "The body knows before the mind agrees — a farmer feels when a shortcut is wrong before they can justify why."},
        {"name": "Mind-Mastery",  "practice": "Permaculture design",
         "meaning": "Observing a site patiently before intervening; building systems that hold their pattern instead of reacting plot-by-plot.",
         "embodied": "Concentration isn't forcing an outcome; it's staying present long enough for the land's own logic to become visible."},
        {"name": "Wisdom",        "practice": "Regenerative farming",
         "meaning": "Soil health verified by working it season after season, not by theory or certification alone.",
         "embodied": "Hands in soil are a form of knowing that reading about soil can't substitute for."},
    ],
    "perfections": [
        {"name": "Generosity",     "field": "Seed saving, gleaning for the community, pricing that doesn't extract maximum margin from a food-insecure neighborhood.", "trains": "Loosening the grip of ownership over what the land produces."},
        {"name": "Morality",       "field": "Fair wages, chemical-free inputs, honest treatment of land and labor alike.", "trains": "The ethical floor everything else stands on."},
        {"name": "Renunciation",   "field": "Letting a field lie fallow; refusing to over-plant or over-extract even when demand is there.", "trains": "Restraint as strength, not loss."},
        {"name": "Wisdom",         "field": "Reading the soil, the pests, the weather directly — a feedback loop between action and observed result.", "trains": "Experiential knowledge over borrowed theory."},
        {"name": "Effort",         "field": "The unglamorous daily labor — weeding, watering, tending — that compost and cover crops require.", "trains": "Right-directed, sustained exertion, not sporadic bursts."},
        {"name": "Patience",       "field": "Waiting out compost maturation, a three-year soil transition, a slow cover-crop cycle.", "trains": "Regeneration doesn't respond to urgency."},
        {"name": "Truthfulness",   "field": "Transparent sourcing, honest labeling, not overselling 'regenerative' or 'organic' claims.", "trains": "Alignment between what's practiced and what's claimed."},
        {"name": "Determination",  "field": "Staying with a multi-season transition through bad harvests and slow years.", "trains": "Follow-through when the payoff is delayed."},
        {"name": "Loving-Kindness","field": "Care extended to workers, neighbors, pollinators, and the soil microbiome — not just the customer.", "trains": "Goodwill as an active practice, not sentiment."},
        {"name": "Equanimity",     "field": "Steady response to drought, pest pressure, or a bad market — neither panicking nor forcing a reactive fix.", "trains": "Non-reactive stability under real conditions."},
    ],
    "curriculum": [
        {"phase": "Foundations", "week": 1,  "anchor": "Morality (Organic)",        "task": "Learn why the farm refuses synthetic inputs; handle compost, mulch, and amendments hands-on.", "prompt": "What's a shortcut you've taken elsewhere that you now see differently?"},
        {"phase": "Foundations", "week": 2,  "anchor": "Mind-Mastery (Permaculture)","task": "Site observation — map water flow, sun, and plant relationships on one bed before touching it.", "prompt": "What did you notice only because you waited before acting?"},
        {"phase": "Foundations", "week": 3,  "anchor": "Wisdom (Regenerative)",      "task": "Soil test + direct comparison against a conventionally treated plot.", "prompt": "What did the soil tell you that a textbook couldn't?"},
        {"phase": "What You Refuse", "week": 4, "anchor": "Generosity",              "task": "Participate in a gleaning or community harvest distribution.", "prompt": "What did giving away food you helped grow feel like?"},
        {"phase": "What You Refuse", "week": 5, "anchor": "Morality (labor ethics)", "task": "Shadow payroll/labor practices; discuss the fair-wage structure of AgriWorks itself.", "prompt": "How does knowing your own wage is fair change how you work?"},
        {"phase": "What You Refuse", "week": 6, "anchor": "Renunciation",            "task": "Deliberately leave a bed fallow or under-harvest a ready crop.", "prompt": "What did it cost you to hold back, and what did it protect?"},
        {"phase": "What You Sustain", "week": 7, "anchor": "Effort",                 "task": "A full week of unglamorous maintenance — weeding, watering, tool care.", "prompt": "What's the difference between forcing effort and sustaining it?"},
        {"phase": "What You Sustain", "week": 8, "anchor": "Patience",               "task": "Turn and monitor an active compost pile; track a slow crop from seed.", "prompt": "Where else in your life are you rushing something that needs time?"},
        {"phase": "What You Sustain", "week": 9, "anchor": "Determination",          "task": "Work through a real setback — pest damage, weather loss, a failed bed — and replant.", "prompt": "What almost made you quit, and what didn't?"},
        {"phase": "What You Sustain", "week": 10, "anchor": "Mid-program review",     "task": "Cohort discussion connecting Weeks 1–9 to personal values named or discovered so far.", "prompt": "Which value has surprised you by mattering?"},
        {"phase": "What You Extend", "week": 11, "anchor": "Truthfulness",           "task": "Help write honest produce labeling and customer-facing materials.", "prompt": "What's the difference between marketing and honesty?"},
        {"phase": "What You Extend", "week": 12, "anchor": "Loving-Kindness",        "task": "Pollinator habitat work or a care task directed at something that gives nothing back directly.", "prompt": "Who or what did you care for today with no expectation of return?"},
        {"phase": "What You Extend", "week": 13, "anchor": "Equanimity",             "task": "Closing session: respond to a simulated setback (market, weather, staffing) as a group, calmly.", "prompt": "What did thirteen weeks of this practice change about how you react to problems?"},
    ],
    "reflections": [
        "What did you notice today only because you waited before acting?",
        "What did the soil tell you that a textbook couldn't?",
        "Where are you rushing something that needs time?",
        "Who or what did you care for today with no expectation of return?",
        "What's a shortcut you now see differently?",
        "What did it cost you to hold back — and what did it protect?",
        "What almost made you quit, and what didn't?",
        "What's the difference between forcing effort and sustaining it?",
    ],
    # How each dataset reaches the dashboard, for the "source data" link when a
    # widget is expanded. Syncable targets map to a Google Sheet; the rest are
    # edited directly on the Manage Data page.
    "source_labels": {
        "community":      "Community impact sheet",
        "monthly_yield":  "Monthly yield sheet",
        "plots":          "Beds / plots sheet",
        "sustainability": "Sustainability sheet",
        "inputs":         "Soil inputs (NPK) sheet",
        "economics":      "Crop economics sheet",
        "budget":         "Grant budget sheet",
        "csa":            "Farmhand CSA orders export (Excel)",
        "settings":       "Farm settings (Manage Data)",
        "milestones":     "Milestones (Manage Data)",
        "tasks":          "Tasks (Manage Data)",
        "deadlines":      "Deadlines (Manage Data)",
        "framework":      "Purpose Driven Farming framework",
    },
}


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    conn = connect()
    c = conn.cursor()
    c.executescript("""
      CREATE TABLE IF NOT EXISTS plots (
        id       TEXT PRIMARY KEY,
        crop     TEXT NOT NULL,
        acres    REAL NOT NULL DEFAULT 0,
        yield_bu REAL NOT NULL DEFAULT 0,
        status   TEXT NOT NULL DEFAULT 'pending',
        x_pct    REAL NOT NULL DEFAULT 50,
        y_pct    REAL NOT NULL DEFAULT 50
      );
      CREATE TABLE IF NOT EXISTS budget (
        category  TEXT PRIMARY KEY,
        allocated REAL NOT NULL DEFAULT 0,
        spent     REAL NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS milestones (
        id    INTEGER PRIMARY KEY,
        label TEXT NOT NULL,
        date  TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending'
      );
      CREATE TABLE IF NOT EXISTS monthly_yield (
        month   INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
        crop    TEXT NOT NULL,
        bushels REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (month, crop)
      );
      CREATE TABLE IF NOT EXISTS inputs (
        name      TEXT PRIMARY KEY,
        applied   REAL NOT NULL DEFAULT 0,
        benchmark REAL NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value REAL NOT NULL
      );

      -- ── New tables for the expanded scope ──
      CREATE TABLE IF NOT EXISTS widgets (
        wid       TEXT PRIMARY KEY,        -- catalog key, e.g. "yield_line"
        sort      INTEGER NOT NULL DEFAULT 0,
        minimized INTEGER NOT NULL DEFAULT 0,
        visible   INTEGER NOT NULL DEFAULT 1
      );
      CREATE TABLE IF NOT EXISTS community (
        month     INTEGER PRIMARY KEY CHECK (month BETWEEN 1 AND 12),
        lbs_dist  REAL NOT NULL DEFAULT 0,   -- pounds of produce distributed
        families  INTEGER NOT NULL DEFAULT 0,
        volunteer_hrs REAL NOT NULL DEFAULT 0,
        csa_shares INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS sustainability (
        month       INTEGER PRIMARY KEY CHECK (month BETWEEN 1 AND 12),
        carbon_kg   REAL NOT NULL DEFAULT 0, -- kg CO2 sequestered
        water_gal   REAL NOT NULL DEFAULT 0, -- gallons used
        solar_kwh   REAL NOT NULL DEFAULT 0  -- kWh generated
      );
      CREATE TABLE IF NOT EXISTS economics (
        crop        TEXT PRIMARY KEY,
        cost        REAL NOT NULL DEFAULT 0,   -- $ input cost
        revenue     REAL NOT NULL DEFAULT 0,   -- $ revenue / value
        unit        TEXT NOT NULL DEFAULT 'season'
      );
      CREATE TABLE IF NOT EXISTS tasks (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        title     TEXT NOT NULL,
        assignee  TEXT NOT NULL DEFAULT '',
        due       TEXT NOT NULL DEFAULT '',
        priority  TEXT NOT NULL DEFAULT 'medium',
        status    TEXT NOT NULL DEFAULT 'todo'
      );
      CREATE TABLE IF NOT EXISTS deadlines (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        grant     TEXT NOT NULL,
        item      TEXT NOT NULL,
        due       TEXT NOT NULL DEFAULT ''
      );
      -- Roadmap: the farm's phased milestones (funding, launches, ongoing work)
      CREATE TABLE IF NOT EXISTS roadmap (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        phase     TEXT NOT NULL DEFAULT '',      -- e.g. "Near-Term (Sep 2026)"
        item      TEXT NOT NULL,
        detail    TEXT NOT NULL DEFAULT '',
        due       TEXT NOT NULL DEFAULT '',       -- target window
        category  TEXT NOT NULL DEFAULT 'general',-- funding|launch|farm-stand|program|legal|ongoing
        status    TEXT NOT NULL DEFAULT 'todo',   -- todo|in-progress|done
        sort      INTEGER NOT NULL DEFAULT 0
      );
      -- CSA orders (imported from the Farmhand export; one row per order)
      CREATE TABLE IF NOT EXISTS csa_orders (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        order_date TEXT NOT NULL DEFAULT '',   -- ISO yyyy-mm-dd
        month     TEXT NOT NULL DEFAULT '',     -- yyyy-mm
        customer  TEXT NOT NULL DEFAULT '',
        email     TEXT NOT NULL DEFAULT '',
        phone     TEXT NOT NULL DEFAULT '',
        location  TEXT NOT NULL DEFAULT '',
        zone      TEXT NOT NULL DEFAULT '',
        dietary   TEXT NOT NULL DEFAULT '',
        status    TEXT NOT NULL DEFAULT '',
        items     TEXT NOT NULL DEFAULT '{}'    -- JSON {item: qty}
      );
      -- Editable CSA unit prices (source export has no price column)
      CREATE TABLE IF NOT EXISTS csa_prices (
        item  TEXT PRIMARY KEY,
        price REAL NOT NULL DEFAULT 0
      );
      -- Google Sheets connections: one row per data table that can sync
      CREATE TABLE IF NOT EXISTS sheet_sources (
        target      TEXT PRIMARY KEY,   -- which table this feeds, e.g. "plots"
        sheet_url   TEXT NOT NULL DEFAULT '',
        enabled     INTEGER NOT NULL DEFAULT 0,
        last_sync   TEXT NOT NULL DEFAULT '',
        last_status TEXT NOT NULL DEFAULT ''
      );
    """)

    # ── Seed first-run data ──
    if c.execute("SELECT COUNT(*) FROM plots").fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO plots VALUES (?,?,?,?,?,?,?)",
            [
                ("Bed-1",  "Callaloo",     0.1, 320, "on-track", 25, 30),
                ("Bed-2",  "Sweet Potato", 0.2, 410, "on-track", 42, 22),
                ("Bed-3",  "Okra",         0.1, 180, "at-risk",  68, 55),
                ("Bed-4",  "Cover Crop",   0.2,   0, "delayed",  38, 72),
                ("Bed-5",  "Collards",     0.1, 260, "complete", 50, 45),
                ("Bed-6",  "Cerasee",      0.1, 140, "on-track", 60, 28),
            ],
        )
        c.executemany(
            "INSERT INTO budget VALUES (?,?,?)",
            [
                ("Staff & Labor",   95000, 71000),
                ("Equipment",       40000, 28000),
                ("Seeds & Inputs",  22000, 15500),
                ("Irrigation",      18000, 11200),
                ("Education",       26000, 9000),
                ("Admin",           14000, 4200),
            ],
        )
        c.executemany(
            "INSERT INTO milestones VALUES (?,?,?,?)",
            [
                (1, "Grant Awarded",          "Jan 2026", "done"),
                (2, "Site & Soil Assessment", "Feb 2026", "done"),
                (3, "Spring Planting",        "Mar 2026", "done"),
                (4, "Mid-Season Report",      "Jun 2026", "active"),
                (5, "Fall Harvest",           "Sep 2026", "pending"),
                (6, "Annual Impact Report",   "Dec 2026", "pending"),
            ],
        )
        yields = {
            "Callaloo":     [0, 20, 60, 120, 180, 240, 300, 320, 210, 90, 0, 0],
            "Sweet Potato": [0, 0, 0, 40, 110, 190, 280, 360, 410, 220, 0, 0],
            "Collards":     [80, 120, 160, 200, 240, 180, 60, 0, 40, 160, 220, 260],
        }
        c.executemany(
            "INSERT INTO monthly_yield VALUES (?,?,?)",
            [(m + 1, crop, bu) for crop, row in yields.items()
             for m, bu in enumerate(row)],
        )
        c.executemany(
            "INSERT INTO inputs VALUES (?,?,?)",
            [
                ("Nitrogen (N)",   38, 45),
                ("Phosphorus (P)", 22, 28),
                ("Potassium (K)",  41, 50),
                ("Organic Matter", 6.2, 5.0),
                ("Compost",        12, 10),
            ],
        )
        c.executemany(
            "INSERT INTO settings VALUES (?,?)",
            [
                ("soil_moisture", 44),
                ("soil_health",   7.8),
                ("grant_total",   215000),
            ],
        )
        # Community impact (Jan–Dec)
        community = [
            (1, 180, 22, 40, 18), (2, 240, 28, 55, 20), (3, 420, 41, 72, 24),
            (4, 680, 58, 96, 30), (5, 910, 73, 120, 34), (6, 1180, 88, 142, 38),
            (7, 1320, 95, 150, 40), (8, 1410, 102, 138, 40), (9, 980, 80, 110, 36),
            (10, 540, 52, 78, 28), (11, 260, 30, 50, 20), (12, 150, 18, 32, 16),
        ]
        c.executemany("INSERT INTO community VALUES (?,?,?,?,?)", community)
        # Sustainability (carbon kg, water gal, solar kWh) per month
        sustain = [
            (1, 210, 4200, 380), (2, 240, 4600, 440), (3, 380, 6800, 560),
            (4, 520, 9200, 680), (5, 690, 12400, 760), (6, 820, 15600, 820),
            (7, 910, 17200, 880), (8, 870, 16400, 840), (9, 640, 11800, 700),
            (10, 410, 7400, 560), (11, 250, 4800, 420), (12, 190, 3900, 360),
        ]
        c.executemany("INSERT INTO sustainability VALUES (?,?,?,?)", sustain)
        # Economics — cost vs revenue per crop, per season
        c.executemany(
            "INSERT INTO economics VALUES (?,?,?,?)",
            [
                ("Callaloo",     420, 1180, "season"),
                ("Sweet Potato", 510, 1620, "season"),
                ("Okra",         360,  640, "season"),
                ("Collards",     390, 1240, "season"),
                ("Cerasee",      280,  980, "season"),
            ],
        )
        # Tasks
        c.executemany(
            "INSERT INTO tasks (title, assignee, due, priority, status) VALUES (?,?,?,?,?)",
            [
                ("Order spring seed stock",        "Maria",      "2026-02-15", "high",   "done"),
                ("Repair Bed-4 drip line",         "Volunteer",  "2026-06-25", "high",   "in-progress"),
                ("Submit mid-season grant report", "Madeline",   "2026-06-30", "high",   "in-progress"),
                ("Schedule June CSA pickups",      "Maria",      "2026-06-20", "medium", "todo"),
                ("Soil test — beds 3 & 4",         "Volunteer",  "2026-07-05", "medium", "todo"),
                ("Plan fall cover crop rotation",  "Director",   "2026-08-01", "low",    "todo"),
            ],
        )
        # Grant deadlines
        c.executemany(
            "INSERT INTO deadlines (grant, item, due) VALUES (?,?,?)",
            [
                ("USDA Urban Ag", "Mid-season financial report", "2026-06-30"),
                ("Knight Found.", "Community impact narrative",   "2026-07-15"),
                ("USDA Urban Ag", "Carbon-credit data export",    "2026-09-01"),
                ("City Green Fund","Annual renewal application",  "2026-10-10"),
            ],
        )
        # Default widget layout — everything visible, in catalog order.
        # The embodiment layer leads, so the human/values frame is the first
        # thing seen, not an afterthought below the metrics.
        order = ["field_reflection", "guiding_foundations", "ten_perfections",
                 "community_kpis", "grant_kpi", "yield_kpi", "carbon_kpi",
                 "produce_dist", "yield_line", "budget_chart", "crop_pie",
                 "field_map", "plot_table", "sustainability_trend", "soil_nutrients",
                 "soil_moisture", "budget_progress", "timeline", "csa_shares",
                 "csa_kpis", "csa_orders_line", "csa_shares_pie", "csa_monthly_sales",
                 "csa_orders_table",
                 "econ_table", "margin_chart", "task_board", "roadmap", "deadlines",
                 "water_kpi", "solar_kpi", "agriworks_curriculum"]
        c.executemany(
            "INSERT INTO widgets (wid, sort, minimized, visible) VALUES (?,?,0,1)",
            [(w, i) for i, w in enumerate(order)],
        )
        # Sheet source rows (one per syncable table), disabled by default
        c.executemany(
            "INSERT INTO sheet_sources (target, sheet_url, enabled) VALUES (?,?,0)",
            [(t, "") for t in ("plots", "budget", "monthly_yield", "inputs",
                                "community", "sustainability", "economics")],
        )

    # Migration safety: ensure widget rows exist for any new catalog keys
    existing = {r["wid"] for r in c.execute("SELECT wid FROM widgets")}
    if existing:  # only if widgets table was already seeded
        maxsort = c.execute("SELECT COALESCE(MAX(sort),0) FROM widgets").fetchone()[0]
        for i, wid in enumerate(WIDGET_CATALOG):
            if wid not in existing:
                c.execute("INSERT INTO widgets (wid, sort, minimized, visible) VALUES (?,?,0,1)",
                          (wid, maxsort + 1 + i))

    # Seed the roadmap (idempotent — also populates pre-existing databases).
    if c.execute("SELECT COUNT(*) FROM roadmap").fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO roadmap (phase, item, detail, due, category, status, sort) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                # ── Near-term (September 2026) ──
                ("Near-Term (Sep 2026)", "Florida Blue Community Investments",
                 "Rolling application — submit when ready.", "Sep 2026", "funding", "todo", 0),
                ("Near-Term (Sep 2026)", "Health Foundation of South Florida",
                 "Follow up on rolling inquiry via GOapply.", "Sep 2026", "funding", "todo", 1),
                ("Near-Term (Sep 2026)", "Walmart Spark Good Local Grants",
                 "Submit for both store locations.", "Sep 2026", "funding", "todo", 2),
                ("Near-Term (Sep 2026)", "Co-founder agreement (AI analytics dashboard)",
                 "Move v3 documents toward execution; finalize new LLC structure, Background IP license from HGM, vesting/equity terms.",
                 "Sep 2026", "legal", "in-progress", 3),
                ("Near-Term (Sep 2026)", "Farm field trip outreach campaign",
                 "Launch outreach to schools/childcare centers within 10 miles of Cerasee Farm.",
                 "Sep 2026", "program", "todo", 4),
                ("Near-Term (Sep 2026)", "Tesla vehicle / EV charger donation request",
                 "Submit or follow up.", "Sep 2026", "funding", "todo", 5),
                # ── October 2026 — Commercial Launch Target ──
                ("October 2026 — Commercial Launch", "UGW Enterprises (Urban Rootz)",
                 "Execute launch per Business Plan v8.", "Oct 2026", "launch", "todo", 6),
                ("October 2026 — Commercial Launch", "BIO-copia LLC",
                 "Execute launch per Business Plan v7.", "Oct 2026", "launch", "todo", 7),
                ("October 2026 — Commercial Launch", "HGM Ventures",
                 "Align entity-wide launch activities per Business Plan v6.", "Oct 2026", "launch", "todo", 8),
                ("October 2026 — Commercial Launch", "Entity Structure Memo v6",
                 "Confirm it reflects the final launch structure across all entities.", "Oct 2026", "legal", "todo", 9),
                # ── November 2026 — Farm Stand ──
                ("November 2026 — Farm Stand", "Farm stand launch",
                 "Timed to harvest readiness — finalize name decision (Drigo's vs. alternative).",
                 "Nov 2026", "farm-stand", "todo", 10),
                ("November 2026 — Farm Stand", "Signage, staffing & POS setup",
                 "Confirm ahead of launch.", "Nov 2026", "farm-stand", "todo", 11),
                ("November 2026 — Farm Stand", "Juice bar coordination",
                 "Coordinate with juice bar structure if Home Depot grant funds materialize in time.",
                 "Nov 2026", "farm-stand", "todo", 12),
                # ── Ongoing / no fixed deadline ──
                ("Ongoing / No Fixed Deadline", "Recognition & Attribution clause",
                 "Roll out across all active/new UGW consulting contracts.", "Ongoing", "legal", "in-progress", 13),
                ("Ongoing / No Fixed Deadline", "Resilient Kids curriculum",
                 "Pursue district-level adoption conversations.", "Ongoing", "program", "todo", 14),
                ("Ongoing / No Fixed Deadline", "St. Rose of Lima school garden",
                 "Monitor implementation against the $10,000 budget plan.", "Ongoing", "program", "in-progress", 15),
                ("Ongoing / No Fixed Deadline", "Merged operating budget workbook",
                 "Keep reconciled as nonprofit/LLC financials evolve; revisit paid-intern staffing model (FIU/UM/MDC) as programs scale.",
                 "Ongoing", "ongoing", "in-progress", 16),
                ("Ongoing / No Fixed Deadline", "Chicken incubation",
                 "Ongoing personal project, no external deadline.", "Ongoing", "ongoing", "in-progress", 17),
                ("Ongoing / No Fixed Deadline", "The Embodied TimeMap",
                 "Maintain Excel/HTML versions in parallel as needed.", "Ongoing", "ongoing", "in-progress", 18),
            ],
        )

    # Seed CSA orders + prices from the bundled Farmhand export (idempotent).
    if c.execute("SELECT COUNT(*) FROM csa_orders").fetchone()[0] == 0:
        try:
            import csa_seed
            c.executemany(
                "INSERT INTO csa_orders (order_date, month, customer, email, phone, "
                "location, zone, dietary, status, items) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(o["date"], o["month"], o["name"], o["email"], o["phone"],
                  o["location"], o["zone"], o["dietary"], o["status"],
                  json.dumps(o["items"])) for o in csa_seed.CSA_ORDERS],
            )
            if c.execute("SELECT COUNT(*) FROM csa_prices").fetchone()[0] == 0:
                c.executemany("INSERT INTO csa_prices (item, price) VALUES (?,?) "
                              "ON CONFLICT(item) DO NOTHING",
                              list(csa_seed.DEFAULT_PRICES.items()))
        except Exception as e:
            print(f"[csa] could not seed CSA orders: {e}")

    conn.commit()
    conn.close()


def csa_analytics(conn):
    """Aggregate CSA orders into the numbers the dashboard shows."""
    orders = []
    for r in conn.execute("SELECT * FROM csa_orders ORDER BY order_date, id"):
        d = dict(r)
        try:
            d["items_map"] = json.loads(d.get("items") or "{}")
        except (ValueError, TypeError):
            d["items_map"] = {}
        orders.append(d)
    prices = {r["item"]: r["price"] for r in conn.execute("SELECT * FROM csa_prices")}

    share_items = ["Small Farm Box", "Regular Farm Share", "Small Fruit Box"]
    share_counts = {s: 0 for s in share_items}
    item_units = {}
    per_customer = {}
    monthly = {}          # month -> {orders, units, revenue}
    total_units = 0
    total_revenue = 0.0

    for o in orders:
        cust = (o.get("email") or o.get("customer") or "").strip().lower()
        per_customer[cust] = per_customer.get(cust, 0) + 1
        order_units = 0
        order_rev = 0.0
        for item, qty in o["items_map"].items():
            qty = qty or 0
            item_units[item] = item_units.get(item, 0) + qty
            if item in share_counts:
                share_counts[item] += qty
            order_units += qty
            order_rev += qty * prices.get(item, 0)
        total_units += order_units
        total_revenue += order_rev
        m = o.get("month") or "unknown"
        mm = monthly.setdefault(m, {"month": m, "orders": 0, "units": 0, "revenue": 0.0})
        mm["orders"] += 1
        mm["units"] += order_units
        mm["revenue"] += order_rev

    monthly_list = [monthly[k] for k in sorted(monthly)]
    unique = len([c for c in per_customer if c])
    repeat = len([c for c, n in per_customer.items() if c and n > 1])
    most_popular = max(share_counts, key=share_counts.get) if any(share_counts.values()) else "—"

    return {
        "orders": orders,
        "prices": prices,
        "summary": {
            "total_orders": len(orders),
            "unique_customers": unique,
            "repeat_customers": repeat,
            "repeat_pct": round(repeat / unique * 100, 1) if unique else 0,
            "share_counts": share_counts,
            "most_popular_share": most_popular,
            "item_units": item_units,
            "total_units": total_units,
            "grand_total_revenue": round(total_revenue, 2),
            "monthly": monthly_list,
            "date_range": (orders[0]["order_date"] if orders else "",
                           orders[-1]["order_date"] if orders else ""),
        },
    }


def dashboard_payload(conn):
    plots = [dict(r) for r in conn.execute("SELECT * FROM plots ORDER BY id")]
    budget = [dict(r) for r in conn.execute("SELECT * FROM budget ORDER BY rowid")]
    milestones = [dict(r) for r in conn.execute("SELECT * FROM milestones ORDER BY id")]
    inputs = [dict(r) for r in conn.execute("SELECT * FROM inputs ORDER BY rowid")]
    settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    community = [dict(r) for r in conn.execute("SELECT * FROM community ORDER BY month")]
    sustainability = [dict(r) for r in conn.execute("SELECT * FROM sustainability ORDER BY month")]
    economics = [dict(r) for r in conn.execute("SELECT * FROM economics ORDER BY rowid")]
    tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY status, due")]
    deadlines = [dict(r) for r in conn.execute("SELECT * FROM deadlines ORDER BY due")]
    roadmap = [dict(r) for r in conn.execute("SELECT * FROM roadmap ORDER BY sort, id")]
    widgets = [dict(r) for r in conn.execute("SELECT * FROM widgets ORDER BY sort")]
    sheets = [dict(r) for r in conn.execute("SELECT * FROM sheet_sources ORDER BY target")]

    series = {}
    for r in conn.execute("SELECT month, crop, bushels FROM monthly_yield ORDER BY crop, month"):
        series.setdefault(r["crop"], [0] * 12)[r["month"] - 1] = r["bushels"]

    allocated = sum(b["allocated"] for b in budget)
    spent = sum(b["spent"] for b in budget)
    grant_total = settings.get("grant_total", allocated) or allocated
    total_yield = sum(p["yield_bu"] for p in plots)
    total_acres = sum(p["acres"] for p in plots)
    status_counts = {}
    for p in plots:
        status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1
    active = sum(n for s, n in status_counts.items() if s in ("on-track", "at-risk"))

    # Community / sustainability roll-ups
    lbs_total = sum(r["lbs_dist"] for r in community)
    families_peak = max((r["families"] for r in community), default=0)
    volunteer_total = sum(r["volunteer_hrs"] for r in community)
    csa_total = max((r["csa_shares"] for r in community), default=0)
    carbon_total = sum(r["carbon_kg"] for r in sustainability)
    water_total = sum(r["water_gal"] for r in sustainability)
    solar_total = sum(r["solar_kwh"] for r in sustainability)

    return {
        "kpis": {
            "utilization_pct": round(spent / grant_total * 100, 1) if grant_total else 0,
            "spent": spent,
            "grant_total": grant_total,
            "total_yield": total_yield,
            "total_acres": total_acres,
            "crop_count": len({p["crop"] for p in plots}),
            "plots_total": len(plots),
            "plots_active": active,
            "status_counts": status_counts,
            "soil_health": settings.get("soil_health", 0),
            "soil_moisture": settings.get("soil_moisture", 0),
            "lbs_distributed": lbs_total,
            "families_served": families_peak,
            "volunteer_hours": volunteer_total,
            "csa_shares": csa_total,
            "carbon_kg": carbon_total,
            "water_gal": water_total,
            "solar_kwh": solar_total,
        },
        "plots": plots,
        "budget": budget,
        "milestones": milestones,
        "monthly_yield": {"labels": MONTHS, "series": series},
        "inputs": inputs,
        "settings": settings,
        "community": community,
        "sustainability": sustainability,
        "economics": economics,
        "tasks": tasks,
        "deadlines": deadlines,
        "roadmap": roadmap,
        "widgets": widgets,
        "catalog": WIDGET_CATALOG,
        "categories": CATEGORIES,
        "sheets": sheets,
        "months": MONTHS,
        "embodiment": EMBODIMENT,
        "csa": csa_analytics(conn),
    }


# ───────────────────────── Google Sheets sync ─────────────────────────

def sheet_csv_url(url):
    """Turn a normal Google Sheets share URL into a CSV export URL.

    Accepts:
      https://docs.google.com/spreadsheets/d/<ID>/edit#gid=<GID>
      https://docs.google.com/spreadsheets/d/<ID>/edit?gid=<GID>
      …/export?format=csv  (passed through)
    The sheet must be shared as "Anyone with the link — Viewer".
    """
    if "format=csv" in url:
        return url
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_\-]+)", url)
    if not m:
        return None
    sheet_id = m.group(1)
    gid_m = re.search(r"[#?&]gid=(\d+)", url)
    gid = gid_m.group(1) if gid_m else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_sheet_rows(url):
    csv_url = sheet_csv_url(url)
    if not csv_url:
        raise ValueError("Not a recognizable Google Sheets URL")
    req = urllib.request.Request(csv_url, headers={"User-Agent": "AgriGrant/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(raw))
    return [ {(k or "").strip(): (v or "").strip() for k, v in row.items()}
             for row in reader ]


# Map each syncable table to (columns, key columns, casts). Headers in the
# Google Sheet must match the column names (case-insensitive).
SHEET_SCHEMA = {
    "plots":          (["id", "crop", "acres", "yield_bu", "status", "x_pct", "y_pct"],
                       ["id"], {"acres": float, "yield_bu": float, "x_pct": float, "y_pct": float}),
    "budget":         (["category", "allocated", "spent"],
                       ["category"], {"allocated": float, "spent": float}),
    "monthly_yield":  (["month", "crop", "bushels"],
                       ["month", "crop"], {"month": int, "bushels": float}),
    "inputs":         (["name", "applied", "benchmark"],
                       ["name"], {"applied": float, "benchmark": float}),
    "community":      (["month", "lbs_dist", "families", "volunteer_hrs", "csa_shares"],
                       ["month"], {"month": int, "lbs_dist": float, "families": int,
                                   "volunteer_hrs": float, "csa_shares": int}),
    "sustainability": (["month", "carbon_kg", "water_gal", "solar_kwh"],
                       ["month"], {"month": int, "carbon_kg": float,
                                   "water_gal": float, "solar_kwh": float}),
    "economics":      (["crop", "cost", "revenue", "unit"],
                       ["crop"], {"cost": float, "revenue": float}),
}


def sync_table(conn, target):
    """Pull a Google Sheet and upsert it into `target`. Returns rows imported."""
    if target not in SHEET_SCHEMA:
        raise ValueError(f"{target} is not syncable")
    row = conn.execute("SELECT sheet_url FROM sheet_sources WHERE target = ?",
                       (target,)).fetchone()
    if not row or not row["sheet_url"]:
        raise ValueError("No sheet URL configured")
    cols, keys, casts = SHEET_SCHEMA[target]
    rows = fetch_sheet_rows(row["sheet_url"])
    if not rows:
        return 0
    # Normalize header lookup (case-insensitive)
    imported = 0
    cur = conn.cursor()
    for r in rows:
        lower = {k.lower(): v for k, v in r.items()}
        values = {}
        ok = True
        for col in cols:
            if col.lower() not in lower:
                # allow optional unit column to default
                if col == "unit":
                    values[col] = "season"
                    continue
                ok = False
                break
            raw = lower[col.lower()]
            cast = casts.get(col)
            try:
                values[col] = cast(raw) if cast and raw != "" else (raw if not cast else 0)
            except (TypeError, ValueError):
                ok = False
                break
        if not ok:
            continue
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
        sql = (f"INSERT INTO {target} ({','.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates}")
        cur.execute(sql, tuple(values[c] for c in cols))
        imported += 1
    conn.commit()
    return imported


def run_sync(target):
    """Sync one table, recording status. Returns (ok, message)."""
    with connect() as conn:
        try:
            n = sync_table(conn, target)
            conn.execute("UPDATE sheet_sources SET last_sync=?, last_status=? WHERE target=?",
                         (now_iso(), f"OK — {n} rows", target))
            conn.commit()
            return True, f"Imported {n} rows into {target}"
        except (urllib.error.URLError, ValueError, Exception) as e:
            msg = f"Error: {e}"
            conn.execute("UPDATE sheet_sources SET last_sync=?, last_status=? WHERE target=?",
                         (now_iso(), msg[:200], target))
            conn.commit()
            return False, msg


def weekly_scheduler():
    """Background thread: every hour, sync any enabled source whose last sync
    was more than 7 days ago (or never)."""
    while True:
        try:
            with connect() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT target, enabled, last_sync FROM sheet_sources WHERE enabled = 1")]
            for r in rows:
                due = True
                if r["last_sync"]:
                    try:
                        last = datetime.fromisoformat(r["last_sync"])
                        due = (datetime.now(timezone.utc) - last).total_seconds() > 7 * 86400
                    except ValueError:
                        due = True
                if due:
                    ok, msg = run_sync(r["target"])
                    print(f"[weekly-sync] {r['target']}: {msg}")
        except Exception as e:
            print(f"[weekly-sync] scheduler error: {e}")
        time.sleep(3600)  # check hourly; only syncs when 7 days have elapsed


# ───────────────────────────── HTTP handler ─────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/dashboard"):
            super().log_message(fmt, *args)

    # ---- helpers -------------------------------------------------
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def fail(self, msg, status=400):
        self.send_json({"error": msg}, status)

    # ---- GET -----------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/dashboard":
            with connect() as conn:
                self.send_json(dashboard_payload(conn))
        elif path == "/api/catalog":
            self.send_json({"catalog": WIDGET_CATALOG, "categories": CATEGORIES})
        elif path == "/api/plots":
            with connect() as conn:
                self.send_json([dict(r) for r in conn.execute("SELECT * FROM plots ORDER BY id")])
        elif path == "/api/budget":
            with connect() as conn:
                self.send_json([dict(r) for r in conn.execute("SELECT * FROM budget ORDER BY rowid")])
        elif path == "/api/tasks":
            with connect() as conn:
                self.send_json([dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY status, due")])
        elif path == "/api/sheets":
            with connect() as conn:
                self.send_json([dict(r) for r in conn.execute("SELECT * FROM sheet_sources ORDER BY target")])
        elif path.startswith("/api/"):
            self.fail("not found", 404)
        else:
            super().do_GET()

    # ---- POST ----------------------------------------------------
    def do_POST(self):
        path = self.path.split("?")[0]
        body = self.read_body()
        if body is None:
            return self.fail("invalid JSON body")

        if path == "/api/plots":
            if not body.get("id") or not body.get("crop"):
                return self.fail("id and crop are required")
            status = body.get("status", "pending")
            if status not in PLOT_STATUSES:
                return self.fail(f"status must be one of {sorted(PLOT_STATUSES)}")
            try:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO plots VALUES (?,?,?,?,?,?,?)",
                        (body["id"].strip(), body["crop"].strip(),
                         float(body.get("acres", 0)), float(body.get("yield_bu", 0)),
                         status, float(body.get("x_pct", 50)), float(body.get("y_pct", 50))))
            except sqlite3.IntegrityError:
                return self.fail(f"plot {body['id']} already exists", 409)
            except (TypeError, ValueError):
                return self.fail("acres, yield_bu, x_pct, y_pct must be numbers")
            return self.send_json({"ok": True}, 201)

        if path == "/api/tasks":
            if not body.get("title"):
                return self.fail("title is required")
            if body.get("priority", "medium") not in TASK_PRIORITIES:
                return self.fail(f"priority must be one of {sorted(TASK_PRIORITIES)}")
            if body.get("status", "todo") not in TASK_STATUSES:
                return self.fail(f"status must be one of {sorted(TASK_STATUSES)}")
            with connect() as conn:
                cur = conn.execute(
                    "INSERT INTO tasks (title, assignee, due, priority, status) VALUES (?,?,?,?,?)",
                    (body["title"].strip(), body.get("assignee", "").strip(),
                     body.get("due", "").strip(), body.get("priority", "medium"),
                     body.get("status", "todo")))
                tid = cur.lastrowid
            return self.send_json({"ok": True, "id": tid}, 201)

        if path == "/api/deadlines":
            if not body.get("grant") or not body.get("item"):
                return self.fail("grant and item are required")
            with connect() as conn:
                cur = conn.execute(
                    "INSERT INTO deadlines (grant, item, due) VALUES (?,?,?)",
                    (body["grant"].strip(), body["item"].strip(), body.get("due", "").strip()))
                did = cur.lastrowid
            return self.send_json({"ok": True, "id": did}, 201)

        if path == "/api/roadmap":
            if not body.get("item"):
                return self.fail("item is required")
            if body.get("status", "todo") not in ROADMAP_STATUSES:
                return self.fail(f"status must be one of {sorted(ROADMAP_STATUSES)}")
            with connect() as conn:
                maxsort = conn.execute("SELECT COALESCE(MAX(sort),0) FROM roadmap").fetchone()[0]
                cur = conn.execute(
                    "INSERT INTO roadmap (phase, item, detail, due, category, status, sort) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (body.get("phase", "").strip(), body["item"].strip(),
                     body.get("detail", "").strip(), body.get("due", "").strip(),
                     body.get("category", "general").strip(),
                     body.get("status", "todo"), maxsort + 1))
                rid = cur.lastrowid
            return self.send_json({"ok": True, "id": rid}, 201)

        if path == "/api/economics":
            if not body.get("crop"):
                return self.fail("crop is required")
            try:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO economics (crop, cost, revenue, unit) VALUES (?,?,?,?) "
                        "ON CONFLICT(crop) DO UPDATE SET cost=excluded.cost, "
                        "revenue=excluded.revenue, unit=excluded.unit",
                        (body["crop"].strip(), float(body.get("cost", 0)),
                         float(body.get("revenue", 0)), body.get("unit", "season")))
            except (TypeError, ValueError):
                return self.fail("cost and revenue must be numbers")
            return self.send_json({"ok": True}, 201)

        # Add a widget to the layout (or re-show a hidden one)
        if path == "/api/widgets":
            wid = body.get("wid")
            if wid not in WIDGET_CATALOG:
                return self.fail(f"unknown widget '{wid}'")
            with connect() as conn:
                maxsort = conn.execute("SELECT COALESCE(MAX(sort),0) FROM widgets").fetchone()[0]
                conn.execute(
                    "INSERT INTO widgets (wid, sort, minimized, visible) VALUES (?,?,0,1) "
                    "ON CONFLICT(wid) DO UPDATE SET visible=1, minimized=0",
                    (wid, maxsort + 1))
            return self.send_json({"ok": True}, 201)

        # Trigger an immediate Google Sheets sync for one target
        if path == "/api/sheets/sync":
            target = body.get("target")
            if target not in SHEET_SCHEMA:
                return self.fail(f"'{target}' is not syncable")
            ok, msg = run_sync(target)
            return self.send_json({"ok": ok, "message": msg}, 200 if ok else 502)

        return self.fail("not found", 404)

    # ---- PUT -----------------------------------------------------
    def do_PUT(self):
        path = self.path.split("?")[0]
        body = self.read_body()
        if body is None:
            return self.fail("invalid JSON body")

        m = re.fullmatch(r"/api/plots/([\w\-]+)", path)
        if m:
            return self.update_row(
                "plots", "id", m.group(1), body,
                allowed={"crop": str, "acres": float, "yield_bu": float,
                         "status": str, "x_pct": float, "y_pct": float},
                validate=lambda b: (None if b.get("status") in PLOT_STATUSES or "status" not in b
                                    else f"status must be one of {sorted(PLOT_STATUSES)}"))

        m = re.fullmatch(r"/api/budget/([^/]+)", path)
        if m:
            return self.update_row("budget", "category", m.group(1), body,
                                   allowed={"allocated": float, "spent": float})

        m = re.fullmatch(r"/api/milestones/(\d+)", path)
        if m:
            return self.update_row(
                "milestones", "id", int(m.group(1)), body,
                allowed={"state": str, "label": str, "date": str},
                validate=lambda b: (None if b.get("state") in MILESTONE_STATES or "state" not in b
                                    else f"state must be one of {sorted(MILESTONE_STATES)}"))

        m = re.fullmatch(r"/api/inputs/([^/]+)", path)
        if m:
            return self.update_row("inputs", "name", m.group(1), body,
                                   allowed={"applied": float, "benchmark": float})

        m = re.fullmatch(r"/api/economics/([^/]+)", path)
        if m:
            return self.update_row("economics", "crop", m.group(1), body,
                                   allowed={"cost": float, "revenue": float, "unit": str})

        m = re.fullmatch(r"/api/tasks/(\d+)", path)
        if m:
            return self.update_row(
                "tasks", "id", int(m.group(1)), body,
                allowed={"title": str, "assignee": str, "due": str,
                         "priority": str, "status": str},
                validate=lambda b: (
                    f"priority must be one of {sorted(TASK_PRIORITIES)}"
                    if b.get("priority") and b["priority"] not in TASK_PRIORITIES else
                    f"status must be one of {sorted(TASK_STATUSES)}"
                    if b.get("status") and b["status"] not in TASK_STATUSES else None))

        m = re.fullmatch(r"/api/deadlines/(\d+)", path)
        if m:
            return self.update_row("deadlines", "id", int(m.group(1)), body,
                                   allowed={"grant": str, "item": str, "due": str})

        m = re.fullmatch(r"/api/roadmap/(\d+)", path)
        if m:
            return self.update_row(
                "roadmap", "id", int(m.group(1)), body,
                allowed={"phase": str, "item": str, "detail": str, "due": str,
                         "category": str, "status": str, "sort": int},
                validate=lambda b: (None if b.get("status") in ROADMAP_STATUSES or "status" not in b
                                    else f"status must be one of {sorted(ROADMAP_STATUSES)}"))

        m = re.fullmatch(r"/api/csa_prices/(.+)", path)
        if m:
            item = urllib.parse.unquote(m.group(1))
            try:
                price = float(body.get("price"))
            except (TypeError, ValueError):
                return self.fail("price must be a number")
            with connect() as conn:
                conn.execute("INSERT INTO csa_prices (item, price) VALUES (?,?) "
                             "ON CONFLICT(item) DO UPDATE SET price = excluded.price",
                             (item, price))
            return self.send_json({"ok": True})

        m = re.fullmatch(r"/api/settings/([\w]+)", path)
        if m:
            try:
                value = float(body.get("value"))
            except (TypeError, ValueError):
                return self.fail("value must be a number")
            with connect() as conn:
                conn.execute("INSERT INTO settings VALUES (?,?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                             (m.group(1), value))
            return self.send_json({"ok": True})

        # Update widget state: minimized / visible / sort
        m = re.fullmatch(r"/api/widgets/([\w]+)", path)
        if m:
            return self.update_row(
                "widgets", "wid", m.group(1), body,
                allowed={"minimized": int, "visible": int, "sort": int})

        # Update community / sustainability month rows
        m = re.fullmatch(r"/api/community/(\d+)", path)
        if m:
            return self.update_row(
                "community", "month", int(m.group(1)), body,
                allowed={"lbs_dist": float, "families": int,
                         "volunteer_hrs": float, "csa_shares": int})

        m = re.fullmatch(r"/api/sustainability/(\d+)", path)
        if m:
            return self.update_row(
                "sustainability", "month", int(m.group(1)), body,
                allowed={"carbon_kg": float, "water_gal": float, "solar_kwh": float})

        # Configure a Google Sheets source
        m = re.fullmatch(r"/api/sheets/([\w]+)", path)
        if m:
            target = m.group(1)
            if target not in SHEET_SCHEMA:
                return self.fail(f"'{target}' is not syncable")
            return self.update_row(
                "sheet_sources", "target", target, body,
                allowed={"sheet_url": str, "enabled": int})

        if path == "/api/yield":
            try:
                month = int(body["month"])
                crop = str(body["crop"]).strip()
                bushels = float(body["bushels"])
                assert 1 <= month <= 12 and crop
            except (KeyError, TypeError, ValueError, AssertionError):
                return self.fail("body must be {month: 1-12, crop, bushels}")
            with connect() as conn:
                conn.execute("INSERT INTO monthly_yield VALUES (?,?,?) "
                             "ON CONFLICT(month, crop) DO UPDATE SET bushels = excluded.bushels",
                             (month, crop, bushels))
            return self.send_json({"ok": True})

        self.fail("not found", 404)

    # ---- DELETE --------------------------------------------------
    def do_DELETE(self):
        path = self.path.split("?")[0]

        m = re.fullmatch(r"/api/plots/([\w\-]+)", path)
        if m:
            return self.delete_row("plots", "id", m.group(1))

        m = re.fullmatch(r"/api/tasks/(\d+)", path)
        if m:
            return self.delete_row("tasks", "id", int(m.group(1)))

        m = re.fullmatch(r"/api/deadlines/(\d+)", path)
        if m:
            return self.delete_row("deadlines", "id", int(m.group(1)))

        m = re.fullmatch(r"/api/roadmap/(\d+)", path)
        if m:
            return self.delete_row("roadmap", "id", int(m.group(1)))

        m = re.fullmatch(r"/api/economics/([^/]+)", path)
        if m:
            return self.delete_row("economics", "crop", m.group(1))

        # Removing a widget hides it (keeps state so it can be re-added)
        m = re.fullmatch(r"/api/widgets/([\w]+)", path)
        if m:
            with connect() as conn:
                cur = conn.execute("UPDATE widgets SET visible = 0 WHERE wid = ?", (m.group(1),))
            if cur.rowcount == 0:
                return self.fail("widget not found", 404)
            return self.send_json({"ok": True})

        self.fail("not found", 404)

    # ---- shared row ops -----------------------------------------
    def update_row(self, table, key_col, key, body, allowed, validate=None):
        if validate:
            err = validate(body)
            if err:
                return self.fail(err)
        fields, values = [], []
        for col, cast in allowed.items():
            if col in body:
                try:
                    values.append(cast(body[col]))
                except (TypeError, ValueError):
                    return self.fail(f"{col} has invalid type")
                fields.append(f"{col} = ?")
        if not fields:
            return self.fail(f"no editable fields given (allowed: {sorted(allowed)})")
        with connect() as conn:
            cur = conn.execute(
                f"UPDATE {table} SET {', '.join(fields)} WHERE {key_col} = ?",
                (*values, key))
        if cur.rowcount == 0:
            return self.fail(f"{table} row not found", 404)
        self.send_json({"ok": True})

    def delete_row(self, table, key_col, key):
        with connect() as conn:
            cur = conn.execute(f"DELETE FROM {table} WHERE {key_col} = ?", (key,))
        if cur.rowcount == 0:
            return self.fail(f"{table} row not found", 404)
        self.send_json({"ok": True})


if __name__ == "__main__":
    init_db()
    threading.Thread(target=weekly_scheduler, daemon=True).start()
    print(f"AgriGrant backend on http://localhost:{PORT}  (db: {DB_PATH})")
    print("Weekly Google Sheets sync scheduler: running (checks hourly)")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
