#!/usr/bin/env python3
"""AgriGrant Dashboard backend — Cerasee Farm & Urban GreenWorks.

A single-file Python stdlib server (no pip installs) that serves the static
frontend and a JSON REST API backed by SQLite. It is built around a *generic
table registry* (see TABLES below) so new data and new dashboard widgets can be
added/edited entirely from the admin page — nothing is hard-coded per table.

Run:  python3 server.py    →  http://localhost:7654

API
  GET    /api/dashboard            full payload the dashboard renders from
  GET    /api/data/<table>         list rows of a registered table
  POST   /api/data/<table>         insert a row     (body = row fields)
  PUT    /api/data/<table>/<pk>    update a row by primary key
  DELETE /api/data/<table>/<pk>    delete a row by primary key
  PUT    /api/yield                upsert {crop_id, month 1-12, lbs}
  GET    /api/widget-catalog       templates that can be added as widgets
  POST   /api/sync                 pull Google Sheets now  (?table=<name> or all)
  GET    /api/meta                 table schema + categories (drives the admin UI)

Google Sheets: each row in the `sheets` table maps a published-CSV URL to a
target table. A background thread re-syncs every enabled connection weekly; the
admin page also has a "Sync now" button. No Google credentials are required —
the sheet just has to be "Published to the web" as CSV.
"""
import csv
import io
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timezone, date, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pesticide_data  # farm chemical cards + cleaned application log + aggregates
import livestock_data  # egg log, chicken purchases + sourcing (cleaned)

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "agrigrant.db")
PORT = 7654
SYNC_INTERVAL_SECONDS = 7 * 24 * 60 * 60  # weekly

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ─────────────────────────────────────────────────────────────────────────────
# Generic table registry.  Each table declares its primary key, whether the PK
# auto-increments (integer rowid), and a column→type map.  Types: str, int,
# float, json (stored as text, parsed on the way out).  The whole CRUD layer,
# validation, and the admin editor are driven from this single structure, so
# extending the system is a matter of adding an entry here + a seed.
# ─────────────────────────────────────────────────────────────────────────────
TABLES = {
    "crops": {
        "pk": "id", "auto": False, "category": "Crops & Yield", "label": "Crops",
        "cols": {
            "id": str, "name": str, "type": str, "beds": int, "status": str,
            "yield_lbs": float, "cost": float, "price": float,
            "nutrition": str, "culture": str, "herbal": str, "notes": str,
        },
    },
    "crop_yield": {  # surrogate key so it fits the generic CRUD; (crop_id,month) unique
        "pk": "id", "auto": True, "category": "Crops & Yield", "label": "Monthly Harvest",
        "cols": {"id": int, "crop_id": str, "month": int, "lbs": float},
        "unique": ("crop_id", "month"),
    },
    "beds": {
        "pk": "id", "auto": False, "category": "Crops & Yield", "label": "Growing Map (Beds)",
        "cols": {
            "id": str, "name": str, "crop_id": str, "size_sqft": float,
            "status": str, "x_pct": float, "y_pct": float,
        },
    },
    "sustainability": {
        "pk": "metric", "auto": False, "category": "Sustainability", "label": "Sustainability Metrics",
        "cols": {
            "metric": str, "label": str, "value": float, "unit": str,
            "benchmark": float, "note": str,
        },
    },
    "soil_tests": {  # populated from the 3 attached lab/university soil reports
        "pk": "id", "auto": True, "category": "Soil", "label": "Soil Composition Tests",
        "cols": {
            "id": int, "site": str, "analyte": str, "value": float, "unit": str,
            "threshold": float, "test_date": str, "lab": str,
        },
    },
    "crop_log": {  # per-crop tracking aggregated from the seeding + harvest logs (since 2023)
        "pk": "crop", "auto": False, "category": "Crops & Yield", "label": "Crop Tracking Log",
        "cols": {
            "crop": str, "seedlings": int, "trays": int,
            "harvested": float, "germ": float,
        },
    },
    "harvest_trend": {  # monthly harvest totals from the harvest log
        "pk": "period", "auto": False, "category": "Crops & Yield", "label": "Harvest Trend (monthly)",
        "cols": {"period": str, "units": float},
    },
    "community": {
        "pk": "metric", "auto": False, "category": "Community Impact", "label": "Community Impact",
        "cols": {
            "metric": str, "label": str, "value": float, "unit": str,
            "goal": float, "period": str,
        },
    },
    "tasks": {
        "pk": "id", "auto": True, "category": "Operations", "label": "Tasks & Deadlines",
        "cols": {
            "id": int, "title": str, "assignee": str, "role": str, "type": str,
            "priority": str, "start": str, "due": str, "status": str, "notes": str,
        },
    },
    "people": {  # volunteers / interns / employees who can be assigned tasks
        "pk": "id", "auto": True, "category": "Operations", "label": "People (Team)",
        "cols": {
            "id": int, "name": str, "role": str, "phone": str,
            "email": str, "active": int, "notes": str,
        },
    },
    "budget": {
        "pk": "category", "auto": False, "category": "Operations", "label": "Budget",
        "cols": {"category": str, "allocated": float, "spent": float},
    },
    "milestones": {
        "pk": "id", "auto": True, "category": "Operations", "label": "Grant Milestones",
        "cols": {"id": int, "label": str, "date": str, "state": str},
    },
    "inputs": {
        "pk": "name", "auto": False, "category": "Sustainability", "label": "Inputs & Compost",
        "cols": {"name": str, "applied": float, "benchmark": float},
    },
    "chemicals": {  # pesticide/biopesticide reference cards w/ health + env info
        "pk": "id", "auto": False, "category": "Sustainability", "label": "Farm Inputs — Health & Safety",
        "cols": {
            "id": str, "name": str, "active": str, "ptype": str, "origin": str,
            "omri": str, "targets": str, "applications": int, "caution": str,
            "health": str, "environment": str, "pollinators": str, "aquatic": str,
            "sources": "json",
        },
    },
    "pesticide_log": {  # cleaned spray-log applications (2023–2026)
        "pk": "id", "auto": True, "category": "Sustainability", "label": "Pesticide Applications",
        "cols": {
            "id": int, "date": str, "crop": str, "bed": str, "pest": str,
            "scale": int, "product": str, "chemicals": str, "dosage": str, "notes": str,
        },
    },
    "pest_pressure": {  # applications + avg severity by pest (aggregate)
        "pk": "pest", "auto": False, "category": "Sustainability", "label": "Pest Pressure",
        "cols": {"pest": str, "applications": int, "avg_scale": float},
    },
    "pesticide_annual": {  # applications per year (aggregate)
        "pk": "year", "auto": False, "category": "Sustainability", "label": "Applications by Year",
        "cols": {"year": str, "applications": int},
    },
    # ── Livestock — egg production + chicken program (from the 2026 logs) ──────
    "eggs": {
        "pk": "id", "auto": True, "category": "Livestock", "label": "Egg Log (daily)",
        "cols": {"id": int, "date": str, "flock": str, "total": int,
                 "brown": int, "other": int, "feed": str, "staff": str},
    },
    "eggs_monthly": {
        "pk": "month", "auto": False, "category": "Livestock", "label": "Eggs by Month",
        "cols": {"month": str, "label": str, "total": int,
                 "brown": int, "other": int, "avg_per_day": float},
    },
    "livestock_costs": {
        "pk": "id", "auto": True, "category": "Livestock", "label": "Chicken Purchases",
        "cols": {"id": int, "date": str, "item": str, "cost": float,
                 "store": str, "flock": str},
    },
    "chicken_sourcing": {
        "pk": "id", "auto": True, "category": "Livestock", "label": "Chicken Inputs & Suppliers",
        "cols": {"id": int, "product": str, "brand": str, "supplier": str, "notes": str},
    },
    "weather": {  # monthly Miami climate, to compare against harvest over the year
        "pk": "month", "auto": False, "category": "Weather", "label": "Miami Weather (monthly)",
        "cols": {"month": int, "label": str, "rainfall_in": float,
                 "temp_avg_f": float, "temp_high_f": float, "note": str},
    },
    "weather_alerts": {  # impactful events: drought / flood / hurricane / heat / frost
        "pk": "id", "auto": True, "category": "Weather", "label": "Weather Alerts",
        "cols": {"id": int, "type": str, "severity": str, "date": str,
                 "title": str, "note": str, "active": int},
    },
    "partners": {
        "pk": "id", "auto": True, "category": "Partners", "label": "Community Partners",
        "cols": {
            "id": int, "name": str, "type": str, "contact": str,
            "contribution": str, "notes": str,
        },
    },
    "settings": {
        "pk": "key", "auto": False, "category": "Operations", "label": "Project Settings",
        "cols": {"key": str, "value": float},
    },
    "roadmap": {  # wishlist of future data assets / widgets to integrate
        "pk": "id", "auto": True, "category": "Roadmap", "label": "Data Roadmap",
        "cols": {"id": int, "name": str, "category": str, "status": str, "note": str},
    },
    "widgets": {
        "pk": "id", "auto": True, "category": "Dashboard", "label": "Widgets",
        "cols": {
            "id": int, "title": str, "type": str, "category": str,
            "source": str, "config": "json", "position": int, "minimized": int,
        },
    },
    "sheets": {
        "pk": "id", "auto": True, "category": "Integrations", "label": "Google Sheets Sync",
        "cols": {
            "id": int, "target_table": str, "csv_url": str,
            "enabled": int, "last_synced": str, "last_status": str,
        },
    },
}

VALID_STATES = {"milestones": {"done", "active", "pending"}}


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def coldef(t):
    if t is int:
        return "INTEGER"
    if t is float:
        return "REAL"
    return "TEXT"  # str and "json"


def init_db():
    conn = connect()
    c = conn.cursor()
    for name, spec in TABLES.items():
        cols = []
        for col, t in spec["cols"].items():
            if col == spec["pk"]:
                if spec["auto"]:
                    cols.append(f"{col} INTEGER PRIMARY KEY AUTOINCREMENT")
                else:
                    cols.append(f"{col} {coldef(t)} PRIMARY KEY")
            else:
                cols.append(f"{col} {coldef(t)}")
        ddl = f"CREATE TABLE IF NOT EXISTS {name} ({', '.join(cols)}"
        if spec.get("unique"):
            ddl += f", UNIQUE({', '.join(spec['unique'])})"
        ddl += ")"
        c.execute(ddl)
    # Cerasee AI assistant config — kept OUT of the TABLES registry so the API
    # key is never exposed through the generic /api/data or /api/dashboard.
    c.execute("CREATE TABLE IF NOT EXISTS ai_settings (key TEXT PRIMARY KEY, value TEXT)")
    migrate_columns(c)  # add any columns introduced after a DB was first created
    conn.commit()
    seed(conn)
    conn.close()


def migrate_columns(c):
    """Add columns that were introduced after an existing DB was created.
    CREATE TABLE IF NOT EXISTS never alters an existing table, so new columns
    in the registry (e.g. tasks.priority) are backfilled here — non-destructive."""
    for name, spec in TABLES.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({name})")}
        if not have:
            continue  # table will be created fresh above
        for col, t in spec["cols"].items():
            if col not in have:
                c.execute(f"ALTER TABLE {name} ADD COLUMN {col} {coldef(t)}")


def seed(conn):
    c = conn.cursor()

    def empty(t):
        return c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0

    # ── Crops — REAL harvest data aggregated from the UGW harvest logs (2023–25).
    #    yield_lbs and the monthly crop_yield series below come straight from the
    #    logs, so the dashboard reflects what the farm actually harvested.
    if empty("crops"):
        c.executemany(
            "INSERT INTO crops (id,name,type,beds,status,yield_lbs,cost,price,nutrition,culture,herbal,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("PAPA", "Papaya", "Tree Fruit", 4, "on-track", 644.7, 0.40, 2.50,
                 "Vitamin C, vitamin A, folate, fiber, and the enzyme papain.",
                 "A Caribbean favorite eaten ripe or green in salads and stews.",
                 "Papain aids digestion; leaves are brewed traditionally as a tonic.",
                 "Top harvest crop by weight — heaviest in Nov–Dec."),
                ("COLL", "Collard", "Leafy Green", 8, "at-risk", 358.2, 0.45, 3.25,
                 "Excellent source of vitamins K, A, C and calcium.",
                 "Cornerstone of Southern and Black American foodways.",
                 "Supports bone and heart health; nutrient-dense cool-season green.",
                 "Reliable year-round producer; scout for aphids."),
                ("MANG", "Mango", "Tree Fruit", 3, "on-track", 265.5, 0.50, 3.00,
                 "Rich in vitamins A and C, fiber and antioxidants.",
                 "The taste of Caribbean summer — eaten fresh and in juices.",
                 "Leaf and bark infusions used in folk remedies.",
                 "Strong May–June flush from the orchard trees."),
                ("CUCU", "Cucumber", "Vine", 5, "on-track", 225.5, 0.40, 2.75,
                 "Very hydrating; vitamin K and low calorie.",
                 "A cooling staple in salads and farm-stand boxes.",
                 "Soothing for skin and digestion.",
                 "Heavy producer on the trellis in the warm months."),
                ("BELL", "Bell Pepper", "Fruiting", 5, "on-track", 187.5, 0.60, 4.50,
                 "Loaded with vitamin C and A and antioxidants.",
                 "The colorful base of sofrito and stews.",
                 "Carotenoids studied for anti-inflammatory benefits.",
                 "High-value CSA crop; peaks in autumn."),
                ("CABB", "Cabbage", "Leafy Green", 6, "on-track", 175.0, 0.35, 2.25,
                 "Good source of vitamin C, vitamin K and fiber.",
                 "Stewed cabbage is a Caribbean side-dish staple.",
                 "Gut-supportive; traditional poultice green.",
                 "Stores well; steady cool-season yields."),
                ("PAKC", "Pak Choi", "Leafy Green", 6, "on-track", 137.0, 0.50, 3.50,
                 "Vitamins A, C and K plus calcium.",
                 "A stir-fry green bridging Caribbean and Asian kitchens.",
                 "Supports bone health; quick-growing.",
                 "Fast cut-and-come-again crop; strong winter flush."),
                ("CARR", "Carrot", "Root", 5, "on-track", 131.6, 0.40, 2.50,
                 "Beta-carotene, fiber and potassium.",
                 "Grated into slaws and pressed for fresh juice.",
                 "Supports eye health.",
                 "Long-season root; best May–June pulls."),
                ("PUMP", "Pumpkin", "Vine / Squash", 4, "on-track", 129.5, 0.30, 2.00,
                 "Beta-carotene, potassium and fiber.",
                 "The heart of Caribbean pumpkin soup.",
                 "Seeds are nutrient-dense; flesh is soothing.",
                 "Sprawling vines; stores for months after harvest."),
                ("LETT", "Lettuce", "Leafy Green", 5, "complete", 116.9, 0.45, 3.25,
                 "Folate, vitamin A and hydration.",
                 "The fresh salad base for the farm stand.",
                 "Light and cooling.",
                 "Cool-season crop; main flush Jan and May."),
                ("EGGP", "Eggplant", "Fruiting", 4, "on-track", 104.8, 0.50, 3.50,
                 "Fiber and antioxidants (nasunin in the skin).",
                 "Asian eggplant featured in curries and stews.",
                 "Supports heart health.",
                 "Productive across the warm and shoulder months."),
                ("FENN", "Fennel", "Herb / Bulb", 3, "on-track", 104.5, 0.55, 4.00,
                 "Vitamin C, fiber and the aromatic compound anethole.",
                 "Aromatic bulb and fronds used in salads and braises.",
                 "Traditional digestive aid.",
                 "Concentrated spring harvest (big May pull)."),
            ],
        )

    if empty("crop_yield"):
        # Real monthly seasonality (calendar month, summed across 2023–25 logs).
        series = {
            "PAPA": [20.6, 19.8, 0, 0, 41.2, 111.5, 0, 0, 0, 30.2, 153.0, 268.4],
            "COLL": [23.0, 5.0, 8.8, 0, 68.0, 101.0, 0, 0, 0, 0, 50.5, 101.8],
            "MANG": [0, 0, 0, 0, 30.0, 163.5, 0, 0, 0, 0, 72.0, 0],
            "CUCU": [0.8, 1.2, 0, 0, 31.5, 19.5, 0, 0, 0, 0, 132.5, 40.0],
            "BELL": [0, 0, 0, 0, 31.5, 32.0, 0, 0, 0, 0, 104.0, 20.0],
            "CABB": [0, 0, 0, 0, 26.0, 61.5, 0, 0, 0, 0, 87.5, 0],
            "PAKC": [67.1, 6.7, 13.9, 0, 0, 0, 0, 0, 0, 0, 0, 49.2],
            "CARR": [1.0, 5.6, 0, 0, 50.0, 75.0, 0, 0, 0, 0, 0, 0],
            "PUMP": [0, 0, 0, 0, 72.0, 20.0, 0, 0, 0, 0, 7.5, 30.0],
            "LETT": [38.1, 1.8, 0, 0, 77.0, 0, 0, 0, 0, 0, 0, 0],
            "EGGP": [6.4, 9.9, 12.3, 0, 0, 14.5, 0, 0, 0, 0, 24.0, 37.7],
            "FENN": [0, 2.5, 0, 0, 102.0, 0, 0, 0, 0, 0, 0, 0],
        }
        c.executemany(
            "INSERT INTO crop_yield (crop_id,month,lbs) VALUES (?,?,?)",
            [(cid, m + 1, lbs) for cid, row in series.items()
             for m, lbs in enumerate(row)],
        )

    if empty("beds"):
        c.executemany(
            "INSERT INTO beds (id,name,crop_id,size_sqft,status,x_pct,y_pct) VALUES (?,?,?,?,?,?,?)",
            [
                ("B1", "North Bed 1",  "COLL", 200, "at-risk",  22, 28),
                ("B2", "North Bed 2",  "LETT", 120, "complete", 40, 24),
                ("B3", "Trellis Row",  "CUCU", 110, "on-track", 64, 38),
                ("B4", "Pepper Row",   "BELL", 90,  "on-track", 30, 60),
                ("B5", "Orchard",      "PAPA", 260, "on-track", 70, 66),
                ("B6", "Squash Patch", "PUMP", 180, "on-track", 52, 50),
                ("B7", "Root Field",   "CARR", 140, "on-track", 82, 30),
            ],
        )

    if empty("sustainability"):
        c.executemany(
            "INSERT INTO sustainability (metric,label,value,unit,benchmark,note) VALUES (?,?,?,?,?,?)",
            [
                ("carbon",  "Carbon Sequestered", 3.8,  "tons CO₂e", 4.5, "Soil + biomass estimate, YTD"),
                ("water",   "Water Used",         62000, "gallons",  90000, "Drip irrigation + rainfall"),
                ("rainwater", "Rainwater Harvested", 18000, "gallons", 15000, "Cistern capture"),
                ("solar",   "Solar Generation",   5400, "kWh",       5000, "Rooftop array, YTD"),
                ("compost", "Compost Produced",   12500, "lbs",      10000, "On-site closed loop"),
                ("soil_health", "Soil Health Score", 7.6, "/ 10",     8.0, "Avg organic-matter index"),
                ("soil_moisture", "Soil Moisture", 44,   "% VWC",     45, "Target band 35–50%"),
            ],
        )

    if empty("community"):
        c.executemany(
            "INSERT INTO community (metric,label,value,unit,goal,period) VALUES (?,?,?,?,?,?)",
            [
                ("donated",   "Produce Donated",    2100, "lbs",   3000, "YTD"),
                ("families",  "Families Served",     185, "households", 250, "YTD"),
                ("volunteer", "Volunteer Hours",    1340, "hours", 1500, "YTD"),
                ("csa",       "CSA Shares Filled",    48, "shares", 60,  "Current season"),
                ("market",    "Farm-Stand Revenue", 9600, "USD",  12000, "YTD"),
                ("workshops", "Education Workshops",   16, "sessions", 20, "YTD"),
            ],
        )

    if empty("people"):
        c.executemany(
            "INSERT INTO people (name,role,phone,email,active,notes) VALUES (?,?,?,?,?,?)",
            [
                ("Director", "employee", "", "", 1, "Executive Director — grants & partnerships"),
                ("Farm Manager", "employee", "", "", 1, "Day-to-day growing operations"),
                ("Volunteer Crew", "volunteer", "", "", 1, "Rotating weekend volunteers"),
                ("Intern", "intern", "", "", 1, "Seasonal data & field intern"),
            ],
        )

    if empty("tasks"):
        c.executemany(
            "INSERT INTO tasks (title,assignee,role,type,priority,start,due,status,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("Submit USDA mid-year grant report", "Director", "employee", "grant", "high", "2026-06-15", "2026-06-30", "active", "Attach yield + impact data"),
                ("Scout collard beds for aphids", "Volunteer Crew", "volunteer", "task", "high", "2026-06-18", "2026-06-20", "active", "B2 flagged at-risk"),
                ("Order drip-line fittings", "Farm Manager", "employee", "purchase", "medium", "2026-06-20", "2026-06-24", "pending", "Replace cracked Pepper Row line"),
                ("Log weekly harvest weights", "Intern", "intern", "task", "medium", "2026-06-16", "2026-06-21", "active", "Enter into harvest log spreadsheet"),
                ("Harvest & dry sorrel calyces", "Volunteer Crew", "volunteer", "task", "low", "2026-09-10", "2026-09-15", "pending", "For holiday sorrel demand"),
                ("Renew Comb Cutters MOU", "Director", "employee", "todo", "medium", "2026-07-01", "2026-07-10", "pending", "On-site beekeeping partner"),
                ("Plant fall collard succession", "Farm Manager", "employee", "task", "medium", "2026-07-25", "2026-08-01", "pending", "Beds B2, B8"),
                ("Carbon-credit documentation packet", "Director", "employee", "grant", "high", "2026-09-15", "2026-10-01", "pending", "Record-keeping for credits"),
            ],
        )

    if empty("budget"):
        c.executemany(
            "INSERT INTO budget (category,allocated,spent) VALUES (?,?,?)",
            [
                ("Seeds & Seedlings", 8000, 5200),
                ("Soil & Compost",    6000, 4100),
                ("Irrigation",        9000, 6400),
                ("Tools & Equipment", 7000, 5900),
                ("Staff & Stipends", 42000, 28500),
                ("Education & CSA",  12000, 7300),
            ],
        )

    if empty("milestones"):
        c.executemany(
            "INSERT INTO milestones (label,date,state) VALUES (?,?,?)",
            [
                ("Grant Awarded",         "Jan 2026", "done"),
                ("Spring Planting",       "Mar 2026", "done"),
                ("CSA Season Launch",     "May 2026", "done"),
                ("Mid-Year Grant Report", "Jun 2026", "active"),
                ("Fall Harvest & Sorrel", "Oct 2026", "pending"),
                ("Carbon-Credit Filing",  "Dec 2026", "pending"),
            ],
        )

    if empty("inputs"):
        c.executemany(
            "INSERT INTO inputs (name,applied,benchmark) VALUES (?,?,?)",
            [
                ("Compost (lbs/bed)",   120, 100),
                ("Worm Castings",        18,  20),
                ("Fish Emulsion (oz)",   24,  28),
                ("Neem (oz)",             6,   8),
                ("Mulch (cu ft)",        40,  45),
            ],
        )

    # ── Pesticide / biopesticide program — from the real spray log (2023–26) ──
    #    Chemical health & environmental cards summarize EPA + NPIC primary
    #    sources; the log + aggregates come from UGW.pesticide.application.log.
    if empty("chemicals"):
        c.executemany(
            "INSERT INTO chemicals (id,name,active,ptype,origin,omri,targets,applications,"
            "caution,health,environment,pollinators,aquatic,sources) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(ch["id"], ch["name"], ch["active"], ch["ptype"], ch["origin"], ch["omri"],
              ch["targets"], ch.get("applications", 0), ch["caution"], ch["health"],
              ch["environment"], ch["pollinators"], ch["aquatic"], json.dumps(ch["sources"]))
             for ch in pesticide_data.CHEMICALS],
        )
    if empty("pesticide_log"):
        c.executemany(
            "INSERT INTO pesticide_log (date,crop,bed,pest,scale,product,chemicals,dosage,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(r["date"], r["crop"], r["bed"], r["pest"], r["scale"], r["product"],
              r["chemicals"], r["dosage"], r["notes"]) for r in pesticide_data.PESTICIDE_LOG],
        )
    if empty("pest_pressure"):
        c.executemany(
            "INSERT INTO pest_pressure (pest,applications,avg_scale) VALUES (?,?,?)",
            [(p["pest"], p["applications"], p["avg_scale"]) for p in pesticide_data.PEST_PRESSURE],
        )
    if empty("pesticide_annual"):
        c.executemany(
            "INSERT INTO pesticide_annual (year,applications) VALUES (?,?)",
            [(a["year"], a["applications"]) for a in pesticide_data.PESTICIDE_ANNUAL],
        )

    # ── Livestock — egg production + chicken program (2026 logs) ──────────────
    if empty("eggs"):
        c.executemany(
            "INSERT INTO eggs (date,flock,total,brown,other,feed,staff) VALUES (?,?,?,?,?,?,?)",
            [(e["date"], e["flock"], e["total"], e["brown"], e["other"], e["feed"], e["staff"])
             for e in livestock_data.EGGS],
        )
    if empty("eggs_monthly"):
        c.executemany(
            "INSERT INTO eggs_monthly (month,label,total,brown,other,avg_per_day) VALUES (?,?,?,?,?,?)",
            [(m["month"], m["label"], m["total"], m["brown"], m["other"], m["avg_per_day"])
             for m in livestock_data.EGGS_MONTHLY],
        )
    if empty("livestock_costs"):
        c.executemany(
            "INSERT INTO livestock_costs (date,item,cost,store,flock) VALUES (?,?,?,?,?)",
            [(x["date"], x["item"], x["cost"], x["store"], x["flock"])
             for x in livestock_data.LIVESTOCK_COSTS],
        )
    if empty("chicken_sourcing"):
        c.executemany(
            "INSERT INTO chicken_sourcing (product,brand,supplier,notes) VALUES (?,?,?,?)",
            [(s["product"], s["brand"], s["where"], s["notes"])
             for s in livestock_data.CHICKEN_SOURCING],
        )

    if empty("partners"):
        c.executemany(
            "INSERT INTO partners (name,type,contact,contribution,notes) VALUES (?,?,?,?,?)",
            [
                ("Comb Cutters", "Beekeeping", "hello@combcutters.org", "On-site hives + pollination", "Honey sold at farm stand"),
                ("Liberty City Mutual Aid", "Food Distribution", "—", "Weekly produce box pickup", "Reaches 60+ households"),
                ("Roots Collective Farm", "Partner Farm", "—", "Shared seedling starts", "Different growing micro-zone"),
                ("Barry University", "Education / Research", "—", "Student volunteers & data support", "Analytics partnership"),
            ],
        )

    if empty("settings"):
        c.executemany(
            "INSERT INTO settings (key,value) VALUES (?,?)",
            [("grant_total", 84000), ("season_year", 2026)],
        )

    if empty("sheets"):
        c.executemany(
            "INSERT INTO sheets (target_table,csv_url,enabled,last_synced,last_status) VALUES (?,?,?,?,?)",
            [
                ("crops",          "", 0, "", "Not configured"),
                ("crop_yield",     "", 0, "", "Not configured"),
                ("sustainability", "", 0, "", "Not configured"),
                ("community",      "", 0, "", "Not configured"),
                ("tasks",          "", 0, "", "Not configured"),
            ],
        )

    # ── Soil composition — from the 3 attached reports ───────────────────────
    # FL DEP residential SCTL / EPA limits used as the "threshold" reference.
    if empty("soil_tests"):
        c.executemany(
            "INSERT INTO soil_tests (site,analyte,value,unit,threshold,test_date,lab) VALUES (?,?,?,?,?,?,?)",
            [
                # AEL full heavy-metal panel — "Soil From Community Garden" (Workorder M1802425)
                ("Community Garden (AEL)", "Lead",        94.0,  "mg/kg", 400.0, "2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Arsenic",     2.2,   "mg/kg", 2.1,   "2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Cadmium",     0.94,  "mg/kg", 82.0,  "2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Chromium",    9.6,   "mg/kg", 210.0, "2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Cobalt",      0.68,  "mg/kg", 1700.0,"2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Copper",      37.0,  "mg/kg", 150.0, "2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Mercury",     0.13,  "mg/kg", 3.0,   "2018-06-21", "Advanced Environmental Labs"),
                ("Community Garden (AEL)", "Moisture",    29.0,  "%",     0.0,   "2018-06-21", "Advanced Environmental Labs"),
                # Barry University Dept. of Physical Sciences — lead + pH across 3 UGW gardens
                ("Garden 1 (1613 NW 54th St)", "Lead", 190.0, "ppm", 400.0, "2019-01-01", "Barry University"),
                ("Garden 1 (1613 NW 54th St)", "pH",   6.91,  "pH",  0.0,   "2019-01-01", "Barry University"),
                ("Garden 2 (1590 NW 54th St)", "Lead", 91.0,  "ppm", 400.0, "2019-01-01", "Barry University"),
                ("Garden 2 (1590 NW 54th St)", "pH",   7.11,  "pH",  0.0,   "2019-01-01", "Barry University"),
                ("Garden 3 (Brownsville)",     "Lead", 44.0,  "ppm", 400.0, "2019-01-01", "Barry University"),
                ("Garden 3 (Brownsville)",     "pH",   7.38,  "pH",  0.0,   "2019-01-01", "Barry University"),
                ("Control (Barry Miami Shores)", "Lead", 28.0, "ppm", 400.0, "2019-01-01", "Barry University"),
                ("Control (Barry Miami Shores)", "pH",   7.32, "pH",  0.0,   "2019-01-01", "Barry University"),
                # Remediation report — Little Haiti baseline before regenerative remediation
                ("Little Haiti (pre-remediation)", "Lead", 1200.0, "ppm", 400.0, "2010-01-01", "Remediation Protocol"),
                ("Little Haiti (post-remediation)", "Lead", 0.0,  "ppm", 400.0, "2011-01-01", "Yale University"),
            ],
        )

    # ── Crop tracking — aggregated from the seeding + harvest logs (2023–2025) ─
    if empty("crop_log"):
        c.executemany(
            "INSERT INTO crop_log (crop,seedlings,trays,harvested,germ) VALUES (?,?,?,?,?)",
            [
                ("Papaya", 384, 6, 644.7, 76),  ("Collard", 140, 4, 358.2, 62),
                ("Mango", 0, 0, 265.5, 76),     ("Cucumber", 1450, 42, 225.5, 100),
                ("Bell Pepper", 20, 12, 187.5, 90), ("Cabbage", 310, 6, 175.0, 76),
                ("Pak Choi", 2408, 58, 137.0, 66), ("Carrot", 3825, 16, 131.6, 100),
                ("Pumpkin", 0, 0, 129.5, 76),   ("Lettuce", 2220, 46, 116.9, 36),
                ("Eggplant", 122, 16, 104.8, 83), ("Fennel", 382, 5, 104.5, 65),
                ("Tomato", 140, 12, 99.6, 100), ("Banana", 0, 0, 69.2, 76),
                ("Swiss Chard", 600, 22, 66.5, 100), ("Cauliflower", 1200, 36, 52.3, 100),
                ("Arugula", 0, 15, 51.6, 57),   ("Broccoli", 600, 18, 43.3, 72),
                ("Radish", 2626, 24, 38.0, 100), ("Okra", 0, 0, 38.5, 76),
                ("Kale", 360, 13, 32.0, 100),   ("Herbs", 1575, 36, 0.0, 76),
            ],
        )

    if empty("harvest_trend"):
        c.executemany(
            "INSERT INTO harvest_trend (period,units) VALUES (?,?)",
            [
                ("2023-10", 89.5), ("2023-12", 177.4), ("2024-01", 259.6),
                ("2024-02", 150.2), ("2024-03", 104.0), ("2024-05", 782.2),
                ("2024-06", 785.5), ("2024-11", 693.0), ("2024-12", 537.0),
            ],
        )

    # ── Miami weather — monthly climate normals (NOAA-style) for overlay ─────
    if empty("weather"):
        # month, label, rainfall_in, temp_avg_f, temp_high_f, note
        wx = [
            (1,  "Jan", 1.6, 68, 76, "Dry season — cool, low rainfall."),
            (2,  "Feb", 2.2, 69, 78, "Dry season; good for greens."),
            (3,  "Mar", 3.0, 72, 80, "Warming up; irrigation matters."),
            (4,  "Apr", 3.1, 76, 83, "End of dry season."),
            (5,  "May", 5.3, 80, 87, "Wet season begins — growth accelerates."),
            (6,  "Jun", 9.7, 82, 89, "Heavy rains; hurricane season opens Jun 1."),
            (7,  "Jul", 6.5, 84, 91, "Hot and humid; afternoon storms."),
            (8,  "Aug", 8.9, 84, 91, "Peak heat; watch for flooding."),
            (9,  "Sep", 9.8, 83, 89, "Wettest month; hurricane peak."),
            (10, "Oct", 6.3, 80, 86, "Wet season winding down; king tides."),
            (11, "Nov", 3.3, 75, 82, "Dry season returns; big fall harvest."),
            (12, "Dec", 2.3, 70, 78, "Cool and dry; holiday demand."),
        ]
        c.executemany(
            "INSERT INTO weather (month,label,rainfall_in,temp_avg_f,temp_high_f,note) VALUES (?,?,?,?,?,?)",
            wx)

    if empty("weather_alerts"):
        c.executemany(
            "INSERT INTO weather_alerts (type,severity,date,title,note,active) VALUES (?,?,?,?,?,?)",
            [
                ("hurricane", "watch", "2026-06-01", "Atlantic hurricane season (Jun 1 – Nov 30)",
                 "Peak Aug–Oct. Keep a harvest-early plan; secure shade cloth, trellises and seedling trays.", 1),
                ("heat", "advisory", "2026-06-20", "Extreme heat advisory",
                 "Heat index over 100°F. Water beds at dawn and shade tender greens (lettuce, pak choi).", 1),
                ("flood", "watch", "2026-06-15", "Wet-season heavy-rain flooding",
                 "Downpours and king tides pool in low beds. Clear drainage and raise trays off the ground.", 1),
                ("drought", "advisory", "2026-03-01", "Dry-season moisture deficit",
                 "Nov–Apr dry spell. Increase drip irrigation and mulch to hold soil moisture.", 0),
                ("frost", "info", "2026-01-10", "Rare cold snap",
                 "South Florida frost is uncommon but possible. Cover tender crops if temps approach 40°F.", 0),
            ],
        )

    # ── Data roadmap — future assets to integrate (editable suggestions) ─────
    if empty("roadmap"):
        c.executemany(
            "INSERT INTO roadmap (name,category,status,note) VALUES (?,?,?,?)",
            [
                ("Carbon soil testing", "Sustainability", "idea",
                 "Lab CO₂ / organic-matter panels to quantify sequestration for carbon-credit programs."),
                ("CSA impacts", "Community Impact", "idea",
                 "Track CSA shares, member retention, and food-access outcomes over time."),
                ("CSA order hub", "Community Impact", "idea",
                 "Bring the currently-outsourced CSA ordering in-house: orders, pickups, payments."),
                ("Solar output", "Sustainability", "idea",
                 "Daily kWh from the rooftop array (live meter feed or monthly bill import)."),
                ("Water usage", "Sustainability", "idea",
                 "Irrigation draw + rainwater capture, broken out by bed or zone."),
                ("Calendar of events", "Operations", "idea",
                 "Workshops, volunteer days, market dates, and planned harvest windows."),
                ("Task tracker", "Operations", "live",
                 "Already on the dashboard — the Tasks & Deadlines widget."),
                ("Organic certification progress", "Certification", "idea",
                 "Checklist + milestones toward USDA Organic / regenerative certification."),
                ("Comb Cutters hive data", "Partners", "planned",
                 "Honey yield and pollination metrics from the on-site beekeeping partner."),
                ("Weather & growing-degree days", "Crops & Yield", "idea",
                 "Log conditions to correlate with harvest outputs and refine planting."),
            ],
        )

    if empty("widgets"):
        seed_widgets(c)
    else:
        backfill_defaults(c)

    conn.commit()


def default_widgets():
    """Full default dashboard layout. `config` is JSON; `maximize` describes the
    customizable expanded view (e.g. per-crop yield + nutrition + culture)."""
    return [
        # title, type, category, source, config, position, minimized
        ("Total Harvest (YTD)", "kpi", "Overview", "kpi:total_yield",
         {"unit": "lbs", "sub": "kpi:harvest_sub"}, 0, 0),
        ("Families Served", "kpi", "Overview", "kpi:families",
         {"unit": "households", "sub": "kpi:families_sub"}, 1, 0),
        ("Grant Utilization", "kpi", "Overview", "kpi:utilization_pct",
         {"unit": "%", "sub": "kpi:grant_sub"}, 2, 0),
        ("CO₂ Sequestered", "kpi", "Overview", "kpi:carbon",
         {"unit": "tons", "sub": "kpi:carbon_sub"}, 3, 0),

        ("Monthly Harvest by Crop", "line", "Crops & Yield", "crop_yield",
         {"span": 2, "y": "lbs"}, 4, 0),
        ("Crop Status & Profit", "table", "Crops & Yield", "crops",
         {"span": 2,
          "columns": ["name", "type", "beds", "yield_lbs", "margin", "status"],
          "maximize": {"detail": "crop",
                       "panels": ["yield_chart", "nutrition", "culture", "herbal", "economics"]}},
         5, 0),
        ("Harvest Share by Crop", "doughnut", "Crops & Yield", "crops",
         {"span": 2, "value": "yield_lbs", "label": "name"}, 6, 0),
        ("Plant Library", "library", "Crops & Yield", "crops",
         {"span": 2,
          "maximize": {"detail": "crop", "panels": ["nutrition", "culture", "herbal"]}},
         7, 0),

        ("Growing Map", "map", "Crops & Yield", "beds", {"span": 2}, 8, 0),

        ("Sustainability vs Benchmark", "bar", "Sustainability", "sustainability",
         {"span": 2, "value": "value", "compare": "benchmark", "label": "label", "horizontal": True}, 9, 0),
        ("Soil Moisture", "gauge", "Sustainability", "sustain:soil_moisture",
         {"max": 100, "unit": "% VWC", "target": "35–50%"}, 10, 0),
        ("Inputs & Compost", "bar", "Sustainability", "inputs",
         {"value": "applied", "compare": "benchmark", "label": "name", "horizontal": True}, 11, 0),

        ("Community Impact", "progress", "Community Impact", "community",
         {"span": 2, "value": "value", "goal": "goal", "label": "label"}, 12, 0),
        ("Farm-Stand Revenue", "kpi", "Community Impact", "community:market",
         {"unit": "USD", "money": True}, 13, 0),
        ("Volunteer Hours", "kpi", "Community Impact", "community:volunteer",
         {"unit": "hrs"}, 14, 0),

        ("Tasks & Deadlines", "list", "Operations", "tasks", {"span": 2}, 15, 0),
        ("Grant Milestones", "timeline", "Operations", "milestones", {"span": 2}, 16, 0),
        ("Budget: Allocated vs Spent", "bar", "Operations", "budget",
         {"span": 2, "value": "allocated", "compare": "spent", "label": "category", "money": True}, 17, 0),
        ("Budget Progress", "progress", "Operations", "budget",
         {"value": "spent", "goal": "allocated", "label": "category", "money": True}, 18, 0),

        ("Community Partners", "list", "Partners", "partners", {"span": 2}, 19, 0),

        # ── Crop tracking from the real seeding + harvest logs (2023–2025) ────
        ("Harvested Since 2023", "kpi", "Overview", "kpi:log_harvest",
         {"unit": "units", "sub": "kpi:log_sub"}, 20, 0),
        ("Crop Tracking — Planted vs Harvested", "table", "Crops & Yield", "crop_log",
         {"span": 2, "columns": ["crop", "seedlings", "trays", "harvested", "germ"]}, 21, 0),
        ("Top Crops by Harvest (since 2023)", "bar", "Crops & Yield", "crop_log",
         {"span": 2, "value": "harvested", "label": "crop", "horizontal": True, "limit": 12}, 22, 0),
        ("Seedlings Planted by Crop", "bar", "Crops & Yield", "crop_log",
         {"span": 2, "value": "seedlings", "label": "crop", "horizontal": True, "limit": 12}, 23, 0),
        ("Monthly Harvest Trend (since 2023)", "line", "Crops & Yield", "harvest_trend",
         {"span": 2, "x": "period", "y": "units"}, 24, 0),

        # ── Soil composition from the 3 attached soil reports ────────────────
        ("Soil Composition Tracking", "table", "Soil", "soil_tests",
         {"span": 2, "columns": ["site", "analyte", "value", "unit", "threshold", "safety"]}, 25, 0),
        ("Heavy Metals vs Safe Limit (AEL panel)", "bar", "Soil", "soil_tests",
         {"span": 2, "value": "value", "compare": "threshold", "label": "analyte",
          "horizontal": True, "filter": {"site": "Community Garden (AEL)"},
          "exclude": {"analyte": ["Moisture"]}}, 26, 0),
        ("Lead by Garden Site (vs 400 ppm toxic)", "bar", "Soil", "soil_tests",
         {"span": 2, "value": "value", "label": "site", "horizontal": True,
          "filter": {"analyte": "Lead"}}, 27, 0),
        ("Soil pH by Garden", "bar", "Soil", "soil_tests",
         {"span": 2, "value": "value", "label": "site", "horizontal": True,
          "filter": {"analyte": "pH"}}, 28, 0),

        # ── Weather (Miami) ──────────────────────────────────────────────────
        ("Active Weather Alerts", "kpi", "Weather", "kpi:active_alerts",
         {"unit": "active", "sub": "kpi:alerts_sub"}, 29, 0),
        ("Weather Alerts", "list", "Weather", "weather_alerts", {"span": 2}, 30, 0),
        ("Miami Rainfall vs Harvest", "climate", "Weather", "weather", {"span": 2}, 31, 0),

        # ── Pest & spray management (from the real pesticide log, 2023–26) ────
        ("Pest Applications Logged", "kpi", "Sustainability", "kpi:pest_apps",
         {"unit": "applications", "sub": "kpi:pest_apps_sub"}, 32, 0),
        ("Organic Program", "kpi", "Sustainability", "kpi:organic_share",
         {"unit": "%", "sub": "kpi:organic_sub"}, 33, 0),
        ("Products Used — Health & Safety", "chemicals", "Sustainability", "chemicals",
         {"span": 2}, 34, 0),
        ("Applications by Product", "bar", "Sustainability", "chemicals",
         {"span": 2, "value": "applications", "label": "name", "horizontal": True,
          "unit": "applications", "limit": 11}, 35, 0),
        ("Pest Pressure (times treated)", "doughnut", "Sustainability", "pest_pressure",
         {"span": 2, "value": "applications", "label": "pest", "unit": "applications"}, 36, 0),
        ("Spray Applications by Year", "bar", "Sustainability", "pesticide_annual",
         {"span": 2, "value": "applications", "label": "year", "unit": "applications"}, 37, 0),
        ("Recent Pesticide Applications", "table", "Sustainability", "pesticide_log",
         {"span": 2, "columns": ["date", "crop", "pest", "scale", "product"], "limit": 20}, 38, 0),

        # ── Team & task tracker ──────────────────────────────────────────────
        ("Team Roster", "list", "Operations", "people", {"span": 2}, 39, 0),

        # ── Livestock — egg production + chicken program (2026 logs) ──────────
        ("Eggs Collected (2026)", "kpi", "Livestock", "kpi:total_eggs",
         {"unit": "eggs", "sub": "kpi:eggs_sub"}, 40, 0),
        ("Chicken Program Spend", "kpi", "Livestock", "kpi:chicken_spend",
         {"unit": "USD", "money": True, "sub": "kpi:chicken_spend_sub"}, 41, 0),
        ("Eggs Collected by Month", "bar", "Livestock", "eggs_monthly",
         {"span": 2, "value": "total", "label": "label", "unit": "eggs"}, 42, 0),
        ("Egg Type Mix (Brown vs Easter-Egger)", "doughnut", "Livestock", "egg_types",
         {"span": 2, "value": "value", "label": "label", "unit": "eggs"}, 43, 0),
        ("Chicken Purchases", "table", "Livestock", "livestock_costs",
         {"span": 2, "columns": ["date", "item", "cost", "store", "flock"]}, 44, 0),
        ("Chicken Inputs & Suppliers", "list", "Livestock", "chicken_sourcing",
         {"span": 2}, 45, 0),
    ]


def seed_widgets(c):
    c.executemany(
        "INSERT INTO widgets (title,type,category,source,config,position,minimized) "
        "VALUES (?,?,?,?,?,?,?)",
        [(t, ty, cat, src, json.dumps(cfg), pos, mn)
         for t, ty, cat, src, cfg, pos, mn in default_widgets()],
    )


def backfill_defaults(c):
    """Restore any missing default widgets (matched by title) so the dashboard
    self-heals — widgets can no longer be permanently lost. User-added widgets
    are left untouched."""
    existing = {r[0] for r in c.execute("SELECT title FROM widgets")}
    for t, ty, cat, src, cfg, pos, mn in default_widgets():
        if t not in existing:
            c.execute(
                "INSERT INTO widgets (title,type,category,source,config,position,minimized) "
                "VALUES (?,?,?,?,?,?,?)",
                (t, ty, cat, src, json.dumps(cfg), pos, mn))
    # keep the Soil pH widget legible (older DBs seeded it narrow & vertical)
    c.execute("UPDATE widgets SET config=? WHERE title=? AND source='soil_tests'",
              (json.dumps({"span": 2, "value": "value", "label": "site",
                           "horizontal": True, "filter": {"analyte": "pH"}}),
               "Soil pH by Garden"))
    # Enrich tasks that predate the priority/role columns — fill NULLs only, so
    # user edits are never overwritten (idempotent; existing DBs get a complete
    # tracker without reseeding).
    if "tasks" in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        c.execute("UPDATE tasks SET priority='medium' WHERE priority IS NULL OR priority=''")
        c.execute("UPDATE tasks SET role=CASE "
                  "WHEN lower(assignee) LIKE '%volunteer%' THEN 'volunteer' "
                  "WHEN lower(assignee) LIKE '%intern%' THEN 'intern' "
                  "ELSE 'employee' END WHERE role IS NULL OR role=''")


# Templates the user can add from the dashboard "+ Add Widget" menu.
WIDGET_CATALOG = [
    {"title": "Total Harvest (YTD)", "type": "kpi", "category": "Overview", "source": "kpi:total_yield",
     "config": {"unit": "lbs", "sub": "kpi:harvest_sub"}},
    {"title": "Grant Utilization", "type": "kpi", "category": "Overview", "source": "kpi:utilization_pct",
     "config": {"unit": "%", "sub": "kpi:grant_sub"}},
    {"title": "Monthly Harvest by Crop", "type": "line", "category": "Crops & Yield", "source": "crop_yield",
     "config": {"span": 2, "y": "lbs"}},
    {"title": "Crop Status & Profit", "type": "table", "category": "Crops & Yield", "source": "crops",
     "config": {"span": 2, "columns": ["name", "type", "beds", "yield_lbs", "margin", "status"],
                "maximize": {"detail": "crop", "panels": ["yield_chart", "nutrition", "culture", "herbal", "economics"]}}},
    {"title": "Harvest Share by Crop", "type": "doughnut", "category": "Crops & Yield", "source": "crops",
     "config": {"span": 2, "value": "yield_lbs", "label": "name"}},
    {"title": "Plant Library", "type": "library", "category": "Crops & Yield", "source": "crops",
     "config": {"span": 2, "maximize": {"detail": "crop", "panels": ["nutrition", "culture", "herbal"]}}},
    {"title": "Growing Map", "type": "map", "category": "Crops & Yield", "source": "beds", "config": {"span": 2}},
    {"title": "Sustainability vs Benchmark", "type": "bar", "category": "Sustainability", "source": "sustainability",
     "config": {"span": 2, "value": "value", "compare": "benchmark", "label": "label", "horizontal": True}},
    {"title": "Soil Moisture", "type": "gauge", "category": "Sustainability", "source": "sustain:soil_moisture",
     "config": {"max": 100, "unit": "% VWC", "target": "35–50%"}},
    {"title": "Community Impact", "type": "progress", "category": "Community Impact", "source": "community",
     "config": {"span": 2, "value": "value", "goal": "goal", "label": "label"}},
    {"title": "Tasks & Deadlines", "type": "list", "category": "Operations", "source": "tasks", "config": {"span": 2}},
    {"title": "Grant Milestones", "type": "timeline", "category": "Operations", "source": "milestones", "config": {"span": 2}},
    {"title": "Budget: Allocated vs Spent", "type": "bar", "category": "Operations", "source": "budget",
     "config": {"span": 2, "value": "allocated", "compare": "spent", "label": "category", "money": True}},
    {"title": "Community Partners", "type": "list", "category": "Partners", "source": "partners", "config": {"span": 2}},
    {"title": "Crop Tracking — Planted vs Harvested", "type": "table", "category": "Crops & Yield", "source": "crop_log",
     "config": {"span": 2, "columns": ["crop", "seedlings", "trays", "harvested", "germ"]}},
    {"title": "Top Crops by Harvest (since 2023)", "type": "bar", "category": "Crops & Yield", "source": "crop_log",
     "config": {"span": 2, "value": "harvested", "label": "crop", "horizontal": True, "limit": 12}},
    {"title": "Seedlings Planted by Crop", "type": "bar", "category": "Crops & Yield", "source": "crop_log",
     "config": {"span": 2, "value": "seedlings", "label": "crop", "horizontal": True, "limit": 12}},
    {"title": "Monthly Harvest Trend (since 2023)", "type": "line", "category": "Crops & Yield", "source": "harvest_trend",
     "config": {"span": 2, "x": "period", "y": "units"}},
    {"title": "Soil Composition Tracking", "type": "table", "category": "Soil", "source": "soil_tests",
     "config": {"span": 2, "columns": ["site", "analyte", "value", "unit", "threshold", "safety"]}},
    {"title": "Heavy Metals vs Safe Limit (AEL panel)", "type": "bar", "category": "Soil", "source": "soil_tests",
     "config": {"span": 2, "value": "value", "compare": "threshold", "label": "analyte", "horizontal": True,
                "filter": {"site": "Community Garden (AEL)"}, "exclude": {"analyte": ["Moisture"]}}},
    {"title": "Lead by Garden Site (vs 400 ppm toxic)", "type": "bar", "category": "Soil", "source": "soil_tests",
     "config": {"span": 2, "value": "value", "label": "site", "horizontal": True, "filter": {"analyte": "Lead"}}},
    {"title": "Soil pH by Garden", "type": "bar", "category": "Soil", "source": "soil_tests",
     "config": {"span": 2, "value": "value", "label": "site", "horizontal": True, "filter": {"analyte": "pH"}}},
    {"title": "Miami Rainfall vs Harvest", "type": "climate", "category": "Weather", "source": "weather",
     "config": {"span": 2}},
    {"title": "Weather Alerts", "type": "list", "category": "Weather", "source": "weather_alerts",
     "config": {"span": 2}},
    {"title": "Active Weather Alerts", "type": "kpi", "category": "Weather", "source": "kpi:active_alerts",
     "config": {"unit": "active", "sub": "kpi:alerts_sub"}},
]


# ─────────────────────────────────────────────────────────────────────────────
# Payload assembly
# ─────────────────────────────────────────────────────────────────────────────
def rows(conn, table, order=None):
    q = f"SELECT * FROM {table}"
    if order:
        q += f" ORDER BY {order}"
    out = [dict(r) for r in conn.execute(q)]
    if table == "widgets":
        for w in out:
            try:
                w["config"] = json.loads(w["config"]) if w["config"] else {}
            except (TypeError, json.JSONDecodeError):
                w["config"] = {}
    return out


def dashboard_payload(conn):
    crops = rows(conn, "crops", "name")
    yld = rows(conn, "crop_yield")
    sustain = {r["metric"]: r for r in rows(conn, "sustainability")}
    community = {r["metric"]: r for r in rows(conn, "community")}
    budget = rows(conn, "budget", "rowid")

    series = {}
    for r in yld:
        series.setdefault(r["crop_id"], [0] * 12)[r["month"] - 1] = r["lbs"]
    # label series by crop name when available
    name_by_id = {c["id"]: c["name"] for c in crops}
    named_series = {name_by_id.get(cid, cid): row for cid, row in series.items()}

    total_yield = sum(c["yield_lbs"] for c in crops)
    allocated = sum(b["allocated"] for b in budget)
    spent = sum(b["spent"] for b in budget)
    settings = {r["key"]: r["value"] for r in rows(conn, "settings")}
    grant_total = settings.get("grant_total") or allocated or 1

    def cv(metric, key="value", default=0):
        return (community.get(metric) or {}).get(key, default)

    def sv(metric, key="value", default=0):
        return (sustain.get(metric) or {}).get(key, default)

    crop_log = rows(conn, "crop_log", "harvested DESC")
    harvest_trend = rows(conn, "harvest_trend", "period")
    soil_tests = rows(conn, "soil_tests", "rowid")
    log_harvest = sum(r["harvested"] for r in crop_log)
    seedlings_total = sum(r["seedlings"] for r in crop_log)
    germ_vals = [r["germ"] for r in crop_log if r["germ"]]
    germ_avg = round(sum(germ_vals) / len(germ_vals)) if germ_vals else 0
    active_lead = [r for r in soil_tests
                   if r["analyte"] == "Lead" and "remediation" not in r["site"].lower()]
    lead_max = max((r["value"] for r in active_lead), default=0)
    weather = rows(conn, "weather", "month")
    weather_alerts = rows(conn, "weather_alerts", "active DESC, rowid")
    active_alerts = sum(1 for a in weather_alerts if a["active"])

    chemicals = rows(conn, "chemicals", "applications DESC")
    pesticide_log = rows(conn, "pesticide_log", "date DESC, id DESC")
    pest_pressure = rows(conn, "pest_pressure", "applications DESC")
    pesticide_annual = rows(conn, "pesticide_annual", "year")
    people = rows(conn, "people", "role, name")
    organic_share = 100  # every product in the program is OMRI-listed / reduced-risk
    total_apps = sum(a["applications"] for a in pesticide_annual)

    eggs_monthly = rows(conn, "eggs_monthly", "month")
    eggs_log = rows(conn, "eggs", "date DESC, id DESC")
    livestock_costs = rows(conn, "livestock_costs", "id")
    chicken_sourcing = rows(conn, "chicken_sourcing", "id")
    total_eggs = sum(m["total"] for m in eggs_monthly)
    total_brown = sum(m["brown"] for m in eggs_monthly)
    total_other = sum(m["other"] for m in eggs_monthly)
    chicken_spend = round(sum(x["cost"] for x in livestock_costs), 2)

    kpis = {
        "total_yield": round(total_yield),
        "harvest_sub": f"{len(crops)} crops · {sum(c['beds'] for c in crops)} beds",
        "families": round(cv("families")),
        "families_sub": f"goal {round(cv('families','goal'))} households",
        "utilization_pct": round(spent / grant_total * 100, 1) if grant_total else 0,
        "grant_sub": f"${spent:,.0f} of ${grant_total:,.0f}",
        "carbon": sv("carbon"),
        "carbon_sub": f"benchmark {sv('carbon','benchmark')} tons",
        "donated": round(cv("donated")),
        "volunteer": round(cv("volunteer")),
        "market": round(cv("market")),
        "soil_health": sv("soil_health"),
        "soil_moisture": sv("soil_moisture"),
        "solar": sv("solar"),
        "log_harvest": round(log_harvest),
        "log_sub": f"{len(crop_log)} crops · {seedlings_total:,} seedlings · {germ_avg}% germ.",
        "seedlings_total": seedlings_total,
        "germ": germ_avg,
        "lead_max": lead_max,
        "active_alerts": active_alerts,
        "alerts_sub": "impactful events flagged now" if active_alerts else "no active alerts",
        "organic_share": organic_share,
        "organic_sub": f"{len([ch for ch in chemicals if ch['caution']!='info'])} products · all OMRI-listed / reduced-risk",
        "pest_apps": total_apps,
        "pest_apps_sub": f"{pesticide_data.DATE_MIN[:4]}–{pesticide_data.DATE_MAX[:4]} · {len(pest_pressure)} pests tracked",
        "total_eggs": total_eggs,
        "eggs_sub": f"{total_brown} brown · {total_other} Easter-egger/blue · {len(eggs_monthly)} months",
        "chicken_spend": chicken_spend,
        "chicken_spend_sub": f"{len(livestock_costs)} purchases logged",
    }

    return {
        "kpis": kpis,
        "crops": crops,
        "crop_yield": {"labels": MONTHS, "series": named_series, "raw": yld},
        "beds": rows(conn, "beds", "id"),
        "sustainability": rows(conn, "sustainability", "rowid"),
        "community": rows(conn, "community", "rowid"),
        "tasks": rows(conn, "tasks", "due"),
        "budget": budget,
        "milestones": rows(conn, "milestones", "id"),
        "inputs": rows(conn, "inputs", "rowid"),
        "partners": rows(conn, "partners", "id"),
        "crop_log": crop_log,
        "harvest_trend": harvest_trend,
        "soil_tests": soil_tests,
        "weather": weather,
        "weather_alerts": weather_alerts,
        "chemicals": chemicals,
        "pesticide_log": pesticide_log,
        "pest_pressure": pest_pressure,
        "pesticide_annual": pesticide_annual,
        "eggs_monthly": eggs_monthly,
        "eggs": eggs_log,
        "egg_types": [{"label": "Brown", "value": total_brown},
                      {"label": "Easter-Egger / Blue", "value": total_other}],
        "livestock_costs": livestock_costs,
        "chicken_sourcing": chicken_sourcing,
        "people": people,
        "roadmap": rows(conn, "roadmap", "rowid"),
        "settings": settings,
        "widgets": rows(conn, "widgets", "position, id"),
        "sheets": rows(conn, "sheets", "id"),
        "months": MONTHS,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Google Sheets sync (published-CSV, no credentials needed)
# ─────────────────────────────────────────────────────────────────────────────
def sync_sheet(conn, sheet):
    table = sheet["target_table"]
    url = (sheet["csv_url"] or "").strip()
    spec = TABLES.get(table)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not spec:
        return _mark_sheet(conn, sheet["id"], now, f"Unknown table '{table}'")
    if not url:
        return _mark_sheet(conn, sheet["id"], now, "No CSV URL set")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AgriGrant/2.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = [h.strip() for h in (reader.fieldnames or [])]
        colmap = {c.lower(): c for c in spec["cols"]}
        matched = [h for h in headers if h.lower() in colmap]
        if spec["pk"] not in [colmap[h.lower()] for h in matched] and not spec["auto"]:
            return _mark_sheet(conn, sheet["id"], now,
                               f"CSV needs a '{spec['pk']}' column")
        count = 0
        for raw in reader:
            row = {}
            for h in matched:
                col = colmap[h.lower()]
                row[col] = cast_value(spec["cols"][col], raw.get(h))
            if not row:
                continue
            upsert_row(conn, table, spec, row)
            count += 1
        conn.commit()
        return _mark_sheet(conn, sheet["id"], now, f"OK — {count} rows synced")
    except Exception as e:  # noqa: BLE001 — surface any sync failure to the UI
        return _mark_sheet(conn, sheet["id"], now, f"Error: {e}")


def _mark_sheet(conn, sid, when, status):
    conn.execute("UPDATE sheets SET last_synced=?, last_status=? WHERE id=?",
                 (when, status, sid))
    conn.commit()
    return status


def cast_value(t, v):
    if v is None or v == "":
        return 0 if t in (int, float) else ""
    if t is int:
        return int(float(v))
    if t is float:
        return float(v)
    if t == "json":
        return v if isinstance(v, str) else json.dumps(v)
    return str(v)


def upsert_row(conn, table, spec, row):
    pk = spec["pk"]
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != pk)
    conflict = pk
    if spec.get("unique"):
        conflict = ",".join(spec["unique"])
    sql = (f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT({conflict}) DO UPDATE SET {updates}") if updates else (
           f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})")
    conn.execute(sql, [row[c] for c in cols])


def parse_xlsx(data):
    """Read the first worksheet of an .xlsx file (stdlib only — no openpyxl).
    Returns a list of {header: value} dicts using the first row as headers."""
    import zipfile
    from xml.etree import ElementTree as ET
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        r = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in r.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets:
        return []
    ws = ET.fromstring(z.read(sheets[0]))

    def colnum(ref):
        m = re.match(r"([A-Z]+)", ref or "A1")
        s = 0
        for ch in m.group(1):
            s = s * 26 + (ord(ch) - 64)
        return s - 1

    grid = []
    for row in ws.iter(NS + "row"):
        cells = {}
        for c in row.findall(NS + "c"):
            t, v = c.get("t"), c.find(NS + "v")
            val = ""
            if v is not None:
                val = shared[int(v.text)] if t == "s" else v.text
            isv = c.find(NS + "is")
            if isv is not None:
                val = "".join(x.text or "" for x in isv.iter(NS + "t"))
            cells[colnum(c.get("r"))] = val
        grid.append(cells)
    if not grid:
        return []
    width = max((max(c) + 1) if c else 0 for c in grid)
    rows = [[c.get(i, "") for i in range(width)] for c in grid]
    headers = [str(h).strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(str(x).strip() for x in r):
            continue
        out.append({headers[i]: r[i] for i in range(len(headers)) if headers[i]})
    return out


def ingest_records(conn, table, spec, records):
    """Upsert a list of {header: value} dicts into a table. Headers are matched
    to columns case-insensitively; unknown columns are ignored."""
    colmap = {c.lower(): c for c in spec["cols"]}
    count, skipped = 0, 0
    for raw in records:
        row = {}
        for k, v in raw.items():
            col = colmap.get(str(k).strip().lower())
            if col:
                row[col] = cast_value(spec["cols"][col], v)
        if not row or (not spec["auto"] and spec["pk"] not in row):
            skipped += 1
            continue
        upsert_row(conn, table, spec, row)
        count += 1
    conn.commit()
    return count, skipped


def sync_all():
    conn = connect()
    results = []
    for sheet in rows(conn, "sheets"):
        if sheet["enabled"]:
            results.append({"table": sheet["target_table"],
                            "status": sync_sheet(conn, sheet)})
    conn.close()
    return results


def weekly_sync_loop():
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)
        try:
            sync_all()
        except Exception as e:  # noqa: BLE001
            print("Weekly sync error:", e)


# ─────────────────────────────────────────────────────────────────────────────
# Live weather — Open-Meteo (climate) + NWS api.weather.gov (alerts). No API key.
# ─────────────────────────────────────────────────────────────────────────────
MIAMI_LAT, MIAMI_LON = 25.7617, -80.1918
WEATHER_UA = "UrbanGreenWorksAlmanac/1.0 (Cerasee Farm dashboard)"


def _nws_type(event):
    e = (event or "").lower()
    if "hurricane" in e or "tropical" in e: return "hurricane"
    if "flood" in e or "surge" in e: return "flood"
    if "heat" in e: return "heat"
    if "fire" in e or "red flag" in e or "drought" in e: return "drought"
    if "freeze" in e or "frost" in e or "cold" in e or "winter" in e: return "frost"
    if "wind" in e or "tornado" in e: return "wind"
    return "storm"


def _nws_sev(sev):
    return {"Extreme": "warning", "Severe": "warning", "Moderate": "watch",
            "Minor": "advisory", "Unknown": "info"}.get(sev, "info")


def _fetch_json(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": WEATHER_UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def sync_weather(conn):
    """Pull live Miami climate + active NWS alerts into the weather tables."""
    msgs = []
    # 1) Monthly climate — multi-year daily archive, averaged by calendar month.
    try:
        end = date.today() - timedelta(days=5)        # archive lags a few days
        start = end.replace(year=end.year - 3)
        url = ("https://archive-api.open-meteo.com/v1/archive"
               f"?latitude={MIAMI_LAT}&longitude={MIAMI_LON}"
               f"&start_date={start}&end_date={end}"
               "&daily=precipitation_sum,temperature_2m_mean,temperature_2m_max"
               "&temperature_unit=fahrenheit&precipitation_unit=inch"
               "&timezone=America%2FNew_York")
        d = _fetch_json(url)["daily"]
        times, pr, tm, tx = d["time"], d["precipitation_sum"], d["temperature_2m_mean"], d["temperature_2m_max"]
        ym_rain = {}                                  # (year,month) -> precip sum
        mean_acc = {m: [0.0, 0] for m in range(1, 13)}
        max_acc = {m: [0.0, 0] for m in range(1, 13)}
        for i, t in enumerate(times):
            y, m = int(t[0:4]), int(t[5:7])
            ym_rain[(y, m)] = ym_rain.get((y, m), 0.0) + (pr[i] or 0)
            if tm[i] is not None: mean_acc[m][0] += tm[i]; mean_acc[m][1] += 1
            if tx[i] is not None: max_acc[m][0] += tx[i]; max_acc[m][1] += 1
        rain_by_month = {m: [] for m in range(1, 13)}
        for (y, m), tot in ym_rain.items():
            rain_by_month[m].append(tot)
        n = 0
        for m in range(1, 13):
            rl = rain_by_month[m]
            rain = round(sum(rl) / len(rl), 1) if rl else 0
            tav = round(mean_acc[m][0] / mean_acc[m][1]) if mean_acc[m][1] else 0
            thi = round(max_acc[m][0] / max_acc[m][1]) if max_acc[m][1] else 0
            conn.execute(
                "INSERT INTO weather (month,label,rainfall_in,temp_avg_f,temp_high_f,note) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(month) DO UPDATE SET rainfall_in=excluded.rainfall_in, "
                "temp_avg_f=excluded.temp_avg_f, temp_high_f=excluded.temp_high_f, note=excluded.note",
                (m, MONTHS[m - 1], rain, tav, thi,
                 f"Live · {start.year}–{end.year} avg (Open-Meteo)"))
            n += 1
        conn.commit()
        msgs.append(f"Climate: {n} months from Open-Meteo ({start.year}-{end.year}).")
    except Exception as e:  # noqa: BLE001
        msgs.append(f"Climate sync failed: {e}")

    # 2) Active alerts — NWS for the Miami point.
    try:
        d = _fetch_json(f"https://api.weather.gov/alerts/active?point={MIAMI_LAT},{MIAMI_LON}",
                        accept="application/geo+json")
        feats = d.get("features", [])
        conn.execute("DELETE FROM weather_alerts")
        cnt = 0
        for f in feats:
            p = f.get("properties", {})
            ev = p.get("event", "Weather Alert")
            note = (p.get("headline") or p.get("description") or "").replace("\n", " ").strip()[:240]
            conn.execute(
                "INSERT INTO weather_alerts (type,severity,date,title,note,active) VALUES (?,?,?,?,?,1)",
                (_nws_type(ev), _nws_sev(p.get("severity")),
                 (p.get("effective") or "")[:10], ev, note))
            cnt += 1
        if cnt == 0:
            conn.execute(
                "INSERT INTO weather_alerts (type,severity,date,title,note,active) "
                "VALUES ('storm','info',?,?,?,0)",
                (str(date.today()), "No active alerts",
                 "The National Weather Service reports no active watches or warnings for Miami right now."))
        conn.commit()
        msgs.append(f"Alerts: {cnt} active from NWS.")
    except Exception as e:  # noqa: BLE001
        msgs.append(f"Alert sync failed: {e}")

    set_ai(conn, "weather_last_sync", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    conn.commit()
    return " ".join(msgs)


def weather_loop():
    """Best-effort: sync once shortly after startup, then daily."""
    time.sleep(6)
    while True:
        try:
            conn = connect()
            print("Weather:", sync_weather(conn))
            conn.close()
        except Exception as e:  # noqa: BLE001
            print("Weather sync error:", e)
        time.sleep(24 * 60 * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Cerasee — AI assistant (Anthropic Messages API over stdlib urllib, no SDK)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_AI_MODEL = "claude-opus-4-8"


def get_ai(conn, key):
    r = conn.execute("SELECT value FROM ai_settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_ai(conn, key, value):
    conn.execute(
        "INSERT INTO ai_settings (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))


def ai_system_prompt(conn):
    """Persona + a compact JSON snapshot of the live dashboard for grounding."""
    p = dashboard_payload(conn)
    data = {k: p[k] for k in (
        "kpis", "crops", "crop_log", "harvest_trend", "soil_tests",
        "sustainability", "community", "tasks", "budget", "milestones",
        "partners", "beds", "inputs") if k in p}
    return (
        "You are Cerasee, a warm, knowledgeable assistant for the Urban GreenWorks Almanac dashboard of "
        "Cerasee Farm & Urban GreenWorks — a nonprofit urban farm in Liberty City, Miami, "
        "rooted in Caribbean growing traditions and regenerative agriculture. "
        "Answer the user's questions about the farm using ONLY the dashboard data provided below. "
        "Be concise, friendly, and specific — cite real numbers and units from the data "
        "(pounds harvested, seedlings, soil lead in ppm, budget dollars, etc.). "
        "Use simple dash bullets for lists. If something isn't in the data, say so plainly and "
        "suggest what the farm could start tracking. Never invent figures.\n\n"
        "LIVE DASHBOARD DATA (JSON):\n" + json.dumps(data, default=str)
    )


def call_anthropic(api_key, model, system, question):
    """One-shot Messages API call. Returns the assistant text, or raises
    ValueError with a user-friendly message on failure."""
    payload = json.dumps({
        "model": model or DEFAULT_AI_MODEL,
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": question}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode())["error"]["message"]
        except Exception:  # noqa: BLE001
            detail = f"HTTP {e.code}"
        if e.code == 401:
            raise ValueError("That API key was rejected. Check it under Manage Data -> Cerasee.")
        if e.code == 429:
            raise ValueError("Cerasee is rate-limited right now — please try again in a moment.")
        raise ValueError(f"Anthropic API error: {detail}")
    except urllib.error.URLError as e:
        raise ValueError(f"Couldn't reach the Anthropic API ({e.reason}). "
                         "Check the server's internet connection.")
    if data.get("stop_reason") == "refusal":
        return "I'm sorry — I can't help with that particular request."
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip() or "(Cerasee returned an empty response.)"


# ─────────────────────────────────────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/dashboard"):  # keep poll noise down
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

    def coerce(self, spec, body, require_all=False):
        """Validate/cast a body dict against a table spec. Returns (row, error)."""
        row, pk, auto = {}, spec["pk"], spec["auto"]
        for col, t in spec["cols"].items():
            if col == pk and auto:
                continue  # autoincrement — never set by client
            if col in body and body[col] is not None:
                try:
                    row[col] = cast_value(t, body[col])
                except (TypeError, ValueError):
                    return None, f"{col} must be a {getattr(t,'__name__',t)}"
            elif require_all and col == pk:
                return None, f"{pk} is required"
        return row, None

    # ---- routing -------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/dashboard":
            with connect() as conn:
                self.send_json(dashboard_payload(conn))
        elif path == "/api/widget-catalog":
            self.send_json(WIDGET_CATALOG)
        elif path == "/api/ai/status":
            with connect() as conn:
                self.send_json({"configured": bool(get_ai(conn, "api_key")),
                                "model": get_ai(conn, "model") or DEFAULT_AI_MODEL})
        elif path == "/api/weather/status":
            with connect() as conn:
                self.send_json({"last_sync": get_ai(conn, "weather_last_sync") or ""})
        elif path == "/api/meta":
            self.send_json({
                "tables": {n: {"pk": s["pk"], "auto": s["auto"],
                               "label": s["label"], "category": s["category"],
                               "cols": {c: getattr(t, "__name__", t)
                                        for c, t in s["cols"].items()}}
                           for n, s in TABLES.items()},
            })
        elif path.startswith("/api/data/"):
            table = path[len("/api/data/"):].split("/")[0]
            if table not in TABLES:
                return self.fail("unknown table", 404)
            with connect() as conn:
                self.send_json(rows(conn, table))
        elif path.startswith("/api/"):
            self.fail("not found", 404)
        else:
            super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/upload":
            return self.handle_upload()
        if path == "/api/ai/ask":
            return self.handle_ai_ask()
        if path == "/api/weather/sync":
            with connect() as conn:
                msg = sync_weather(conn)
                last = get_ai(conn, "weather_last_sync") or ""
            return self.send_json({"message": msg, "last_sync": last})
        if path == "/api/sync":
            q = parse_qs(urlparse(self.path).query)
            target = (q.get("table") or [None])[0]
            with connect() as conn:
                sheets = [s for s in rows(conn, "sheets")
                          if (target in (None, "all", s["target_table"]))]
                results = [{"table": s["target_table"], "status": sync_sheet(conn, s)}
                           for s in sheets if s["enabled"] or target == s["target_table"]]
            return self.send_json({"results": results})

        m = re.fullmatch(r"/api/data/([\w]+)", path)
        if not m:
            return self.fail("not found", 404)
        table = m.group(1)
        spec = TABLES.get(table)
        if not spec:
            return self.fail("unknown table", 404)
        body = self.read_body()
        if body is None:
            return self.fail("invalid JSON body")
        row, err = self.coerce(spec, body, require_all=True)
        if err:
            return self.fail(err)
        cols = list(row.keys())
        try:
            with connect() as conn:
                conn.execute(
                    f"INSERT INTO {table} ({','.join(cols)}) "
                    f"VALUES ({','.join('?' for _ in cols)})",
                    [row[c] for c in cols])
                new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except sqlite3.IntegrityError as e:
            return self.fail(f"already exists / constraint: {e}", 409)
        self.send_json({"ok": True, "id": new_id}, 201)

    def handle_ai_ask(self):
        """Ask Cerasee a question about the dashboard. Returns 400 with
        error 'no_api_key' if the key hasn't been configured yet."""
        body = self.read_body()
        if body is None:
            return self.fail("invalid JSON body")
        question = (body.get("question") or "").strip()
        if not question:
            return self.fail("question is required")
        with connect() as conn:
            api_key = get_ai(conn, "api_key")
            model = get_ai(conn, "model") or DEFAULT_AI_MODEL
            if not api_key:
                return self.send_json({
                    "error": "no_api_key",
                    "message": "To ask Cerasee anything, add your Anthropic API key in the "
                               "backend first (Manage Data -> Cerasee)."}, 400)
            system = ai_system_prompt(conn)
        try:
            answer = call_anthropic(api_key, model, system, question)
        except ValueError as e:
            return self.send_json({"error": "ai_error", "message": str(e)}, 502)
        self.send_json({"answer": answer, "model": model})

    def handle_upload(self):
        """Import a spreadsheet uploaded as the raw request body.
        Query: ?table=<name>&name=<filename>.  Supports .xlsx and .csv."""
        q = parse_qs(urlparse(self.path).query)
        table = (q.get("table") or [""])[0]
        fname = (q.get("name") or [""])[0].lower()
        spec = TABLES.get(table)
        if not spec:
            return self.fail("unknown target table", 404)
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else b""
        if not data:
            return self.fail("no file received")
        try:
            if fname.endswith(".csv") or fname.endswith(".txt"):
                text = data.decode("utf-8-sig", errors="replace")
                records = list(csv.DictReader(io.StringIO(text)))
            elif fname.endswith(".xlsx"):
                records = parse_xlsx(data)
            else:
                return self.fail("please upload a .xlsx or .csv file "
                                 "(Word/PDF documents can't be auto-mapped to a table)")
        except Exception as e:  # noqa: BLE001
            return self.fail(f"could not read file: {e}")
        if not records:
            return self.fail("no data rows found in the file")
        try:
            with connect() as conn:
                count, skipped = ingest_records(conn, table, spec, records)
        except sqlite3.Error as e:
            return self.fail(f"import failed: {e}")
        note = f"Imported {count} row(s) into {table}"
        if skipped:
            note += f" ({skipped} skipped — missing '{spec['pk']}' or no matching columns)"
        return self.send_json({"ok": True, "count": count, "skipped": skipped, "message": note})

    def do_PUT(self):
        path = self.path.split("?")[0]
        body = self.read_body()
        if body is None:
            return self.fail("invalid JSON body")

        if path == "/api/ai/config":
            with connect() as conn:
                if body.get("api_key"):
                    set_ai(conn, "api_key", str(body["api_key"]).strip())
                if body.get("model"):
                    set_ai(conn, "model", str(body["model"]).strip())
            return self.send_json({"ok": True})

        if path == "/api/yield":
            try:
                crop_id = str(body["crop_id"]).strip()
                month = int(body["month"])
                lbs = float(body["lbs"])
                assert crop_id and 1 <= month <= 12
            except (KeyError, TypeError, ValueError, AssertionError):
                return self.fail("body must be {crop_id, month 1-12, lbs}")
            with connect() as conn:
                conn.execute(
                    "INSERT INTO crop_yield (crop_id,month,lbs) VALUES (?,?,?) "
                    "ON CONFLICT(crop_id,month) DO UPDATE SET lbs=excluded.lbs",
                    (crop_id, month, lbs))
            return self.send_json({"ok": True})

        m = re.fullmatch(r"/api/data/([\w]+)/(.+)", path)
        if not m:
            return self.fail("not found", 404)
        table, pk_val = m.group(1), m.group(2)
        from urllib.parse import unquote
        pk_val = unquote(pk_val)
        spec = TABLES.get(table)
        if not spec:
            return self.fail("unknown table", 404)
        if table in VALID_STATES and "state" in body and body["state"] not in VALID_STATES[table]:
            return self.fail(f"state must be one of {sorted(VALID_STATES[table])}")
        row, err = self.coerce(spec, body)
        if err:
            return self.fail(err)
        row.pop(spec["pk"], None)  # don't rewrite the key
        if not row:
            return self.fail("no editable fields given")
        sets = ",".join(f"{c}=?" for c in row)
        with connect() as conn:
            cur = conn.execute(
                f"UPDATE {table} SET {sets} WHERE {spec['pk']}=?",
                [*row.values(), pk_val])
        if cur.rowcount == 0:
            return self.fail("row not found", 404)
        self.send_json({"ok": True})

    def do_DELETE(self):
        m = re.fullmatch(r"/api/data/([\w]+)/(.+)", self.path.split("?")[0])
        if not m:
            return self.fail("not found", 404)
        from urllib.parse import unquote
        table, pk_val = m.group(1), unquote(m.group(2))
        spec = TABLES.get(table)
        if not spec:
            return self.fail("unknown table", 404)
        with connect() as conn:
            cur = conn.execute(f"DELETE FROM {table} WHERE {spec['pk']}=?", (pk_val,))
        if cur.rowcount == 0:
            return self.fail("row not found", 404)
        self.send_json({"ok": True})


if __name__ == "__main__":
    init_db()
    threading.Thread(target=weekly_sync_loop, daemon=True).start()
    threading.Thread(target=weather_loop, daemon=True).start()
    print(f"Urban GreenWorks Almanac backend on http://localhost:{PORT}  (db: {DB_PATH})")
    print("Weekly Google Sheets sync is armed. Live Miami weather syncs on startup + daily.")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
