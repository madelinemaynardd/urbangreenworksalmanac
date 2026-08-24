# Future Integration Plan — Deferred Data & Features

**Urban GreenWorks Almanac / Cerasee Farm**
Written Aug 2026. Covers what was intentionally *not* built in this pass, why, and
a concrete step-by-step path (with investments and data-cleaning needed) to finish each.

---

## What shipped in this pass (for context)

- **Pesticide/biopesticide program → Sustainability**: 11 product "Health & Safety" cards
  (neem, insecticidal soap, Bt, PyGanic, Regalia, Cease, Surround, diatomaceous earth, +
  minor inputs) with human-health & environmental notes sourced from **EPA + NPIC (an
  NIH/EPA-cooperative service)**, each with clickable citations; plus 126 logged applications
  (2023–26) charted by product, by pest, and by year, and a recent-applications table.
- **Highly editable task tracker**: tasks now carry assignee, **role** (volunteer/intern/
  employee), **priority**, start/due dates, status, notes; a new **People (Team)** table +
  Team Roster widget. (Text reminders intentionally deferred — see §6.)

Everything below was deferred **because the source data is messy, or the feature needs paid
services / hosting** the project doesn't have yet.

---

## 1. Livestock & Egg Tracking (chicken + egg logs)

**Data quality:** *Good.* `UGW.egg.log.2026` is clean (one sheet per month: date, flock,
eggs collected, egg-type `[Bwn:EE]`, feed brand, staff initials). This is the **easiest**
next win.

**Data cleaning needed (light):**
- Parse the `[3 Bwn; 2 EE]` egg-type strings into two numeric columns (brown vs Easter-egger/
  blue) — a simple regex.
- Normalize Excel serial dates (e.g. `46034`) → ISO dates (same helper already used for the
  pesticide log).
- Drop the running free-text note rows (e.g. "1 of the eggs broke") into a `notes` field
  instead of a data row.
- Reconcile the two flocks (F1 laying hens; F2 the newer/cockerel flock in the purchase log).

**Build steps:**
1. Add tables `eggs` (date, flock, total, brown, other, feed, staff) and `flocks`
   (id, name, birds, breed, status).
2. Add a **Livestock** category (new earth-tone color) + sidebar tab.
3. Widgets: KPI "Eggs This Month", line "Eggs Collected Over Time", doughnut "Egg Type Mix",
   a feed-brand timeline, and a flock roster list.
4. Aggregate monthly totals server-side (like `harvest_trend`).

**Investment:** ~½–1 day of dev; **no** purchases. Ongoing: staff keep logging in the same
sheet, then upload (once §5 upload fix lands) or paste as a published Google Sheet.

---

## 2. Chicken Product Sourcing & Purchase Costs → Sustainability / Operations

**Data quality:** *Good.* `Chicken Product Sourcing` is clean (Product, Brand, Where to buy,
Notes) plus two purchase-tracking sheets (date, item, cost, store) for F1 and F2.

**Data cleaning needed (light):**
- Split the sourcing sheet (a **reference list** — what to buy & where) from the purchase
  sheets (**transactions** — cost over time).
- Normalize costs to numbers and dates to ISO; a few rows have text dates ("March 12th, 2026").

**Build steps:**
1. Table `sourcing` (product, brand, supplier, where_to_buy, needs_approval, notes) →
   a searchable "Approved Inputs & Suppliers" reference widget (supports organic-cert
   record-keeping).
2. Table `livestock_costs` (date, item, cost, store, flock) → a "Chicken Program Spend"
   line/bar + KPI, feeding the budget picture.
3. Optionally link feed brands here to the egg log's feed column.

**Investment:** ~½ day dev; no purchases.

---

## 3. Harvest Log Integration (the big one)

**Data quality:** *Poor / very messy* — this is why it was deferred. `UGW.harvest.log.25-26`
has **10 sheets**, and each row mixes:
- a **crop-code legend** embedded in the far-right columns (`"142 - Collards"`, `"1 - Arugula,
  Astro (4)"`) that must be joined back to the `Crop` codes used in the data cells;
- **dates** as Excel serials *and* free text (`"4/4/ 26"`, `"11/29 /25"`);
- **units that don't reconcile** — sometimes bunches (`# of bunches`), sometimes pounds in a
  note field (`"6.12 pounds"`), sometimes a sales dollar figure;
- **sales lines** interleaved (`"UOP - $114.32"`, `"Kandahar Fruits"`, "Sold To") mid-column;
- OCR-style artifacts and shared-string leakage (stray numbers where a value should be).

**Data cleaning needed (substantial):**
1. Build a **crop-code → crop-name dictionary** from the legend columns (one-time, ~150 codes),
   then map every data row's `Crop` code to a canonical crop.
2. Write a **robust date parser** handling serials + several text formats; flag/repair the
   corrupt ones (we hit the same 1900-date issue in the pesticide log and handled it).
3. **Decide a canonical yield unit** with the farm (pounds preferred) and build a converter:
   parse "X pounds" out of note fields; establish bunch→lb factors per crop where only bunches
   were recorded. *This requires farm input — it's a data-governance decision, not just code.*
4. Separate **sales** (date, crop, amount, price, buyer) from **harvest** (date, crop, weight)
   into two clean tables.
5. Cross-check the derived per-crop totals against the current dashboard crops (which were
   built from an earlier log) and update.

**Build steps:** once cleaned, it feeds the existing crops/crop_yield/harvest_trend tables and
a new `sales` table → a "Revenue by Crop / by Buyer" widget and true **cost-vs-revenue margins**
(ties into the map spec's profit-margin panel).

**Investment:**
- **Time:** this is the largest task — realistically **2–4 focused days**, most of it cleaning
  and farm reconciliation, not coding.
- **Decisions from the farm:** canonical unit, bunch→lb factors, how to treat donations vs
  sales, buyer name normalization (UOP, Kandahar, UGW, etc.).
- **Optional tooling:** none required (stdlib parser), but an AI-assisted cleaning pass (feed
  each messy sheet to Cerasee/Claude to propose normalized rows for human review) would cut the
  time meaningfully. Budget a small API spend if you go that route.

---

## 4. Seeding Log Integration → Growing-Cycle data for the Map

**Data quality:** *Messy* (multi-season sheets, same crop-code legend, serial dates), but it
holds high-value fields: **DTG (days-to-germinate), % germination, seed→succession→harvest
dates, transplant dates, bed seeded**.

**Data cleaning needed (moderate):** same crop-code dictionary and date parser as §3, plus
parsing the `1 (10)` "trays (cells)" notation and the free-text transplant notes ("30 of 40
transplanted").

**Build steps:**
1. Table `crop_cycle` (crop, days_to_germinate, days_to_harvest, harvest_window,
   succession_interval) aggregated from the plan sheets.
2. This is exactly the input the **interactive-map spec** (`SPEC_interactive_farm_map.md`, §2.3
   & §5.1) reserves for "where in the growing cycle is this crop" — so do §4 **with** the map
   build.
3. A "Germination Rate by Crop" and "Seed-to-Harvest Days" widget in Crops & Yield.

**Investment:** ~1–2 days dev + the shared crop-code/date cleaning from §3 (do §3 and §4
together to reuse the cleaning code).

---

## 5. File-Upload Hardening (the bug you hit)

**Confirmed:** the upload error is **not** an API-key problem — upload is pure local parsing
with no external calls. The real limitations are in `parse_xlsx()`:
1. it reads only the **first worksheet**;
2. it requires headers to **exactly match** a target table's columns;
3. it **crashes on messy values** (mixed date formats, `"1 oz per gal"`) when casting to numbers.

**Build steps:**
1. Read **all** worksheets, not just `sheets[0]`; let the user pick the sheet or merge same-header
   sheets.
2. Make casting **tolerant** — on a bad cast, keep the raw string or skip the cell instead of
   erroring, and report a row-level summary ("42 imported, 3 skipped: bad date").
3. Add a **header-mapping preview** step: show detected headers and let the user map them to
   table columns before import (handles `Flock #` → `flock`, etc.).
4. Better messages ("first sheet had no matching columns — did you mean table X?").

**Investment:** ~1 day dev; no purchases. High value because it unlocks §1 and §2 as
self-service uploads instead of code.

---

## 6. Text-Message Reminders for the Task Tracker

**Why deferred:** real SMS cannot work in the current setup, for two structural reasons:
1. **It needs a paid gateway.** Sending texts requires a service like **Twilio** — a paid
   account, a purchased sending phone number (~$1–2/mo + ~$0.008/message), and API credentials.
2. **It needs an always-on host.** Reminders fire on a schedule; the dashboard currently runs
   **on demand on one laptop**, so a scheduler can't fire when that machine is off. Scheduled
   sending requires the app to be **hosted** (see §7).

**Recommended phased path:**
1. **Now (no cost):** the task tracker already stores assignee, phone (on the People table),
   timeline, and priority. Add an in-dashboard **"Due soon / overdue"** reminders panel — visual
   only. This delivers the *reminder logic* with zero infrastructure.
2. **Phase 2 (hosted + Twilio):** once hosted (§7), add a scheduler thread that, on each task's
   timeline, sends an SMS via Twilio to the assignee's phone. Store a `reminders` table
   (task_id, send_at, sent_at, channel).
3. **Consent & compliance:** SMS to volunteers/staff needs **opt-in** and an **opt-out ("reply
   STOP")** flow — build a simple consent flag on the People record. (Anthropic-side note: the
   app would be *sending on people's behalf*, so keep a clear audit log.)

**Investment:**
- Twilio: **~$1–2/month** for a number + **<$0.01 per text**.
- Hosting: see §7.
- Dev: ~1 day for the scheduler + Twilio integration once hosting exists; Phase 1 panel is ~2 hrs.
- **Alternative (free, less reliable):** carrier email-to-SMS gateways (e.g.
  `number@vtext.com`) — no Twilio cost but requires an email-sending account, is carrier-specific,
  and often lands in spam. Not recommended for anything staff rely on.

---

## 7. Hosting / Deployment (unlocks §6 and live features)

**Why it matters:** several future features (SMS reminders, always-fresh weather, multi-user
access, mobile field entry) need the app to run **continuously at a URL**, not on one laptop.

**Options, cheapest first:**
- **Small cloud VM / PaaS** (e.g. a $5–10/month instance, or a free-tier hobby host): run
  `server.py` continuously; the SQLite file lives on a persistent disk. Simplest lift — the app
  is already a single self-contained server.
- Add **basic logins** (admin vs volunteer) once it's multi-user, so the Director controls who
  can edit.
- Package as an installable **PWA** for phone/field use (reuses the existing web app — no
  separate mobile codebase).

**Investment:** **~$5–15/month** hosting; ~1–2 days for deploy + auth. This is the enabling
step for the whole "live / mobile / multi-farm" vision in the V2 roadmap.

---

## Suggested sequence (fastest value first)

| Order | Item | Effort | Cost | Unlocks |
|---|---|---|---|---|
| 1 | Upload hardening (§5) | ~1 day | none | self-service data updates |
| 2 | Livestock & eggs (§1) | ~1 day | none | new dashboard section |
| 3 | Sourcing & chicken costs (§2) | ~½ day | none | organic-cert records |
| 4 | In-app reminders panel (§6.1) | ~2 hrs | none | task nudges, no infra |
| 5 | Hosting + auth (§7) | ~1–2 days | ~$10/mo | live app, mobile, multi-user |
| 6 | SMS reminders (§6.2) | ~1 day | ~$2/mo | text reminders |
| 7 | Seeding log + map cycle (§4) | ~1–2 days | none* | interactive map cycle data |
| 8 | Harvest log + sales (§3) | ~2–4 days | none* | true per-crop margins |

\* No cash cost, but §3/§4 need farm decisions on units and an optional AI-assisted cleaning pass.
