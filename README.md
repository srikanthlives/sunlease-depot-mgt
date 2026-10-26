# Sunlease Depot Management

Fixed bus schedule management for Sunlease electric buses (release 1 of the depot app).
Spec: [sunlease_fixed_bus_schedule_specification.md](sunlease_fixed_bus_schedule_specification.md) · Decisions and build order: [PLAN.md](PLAN.md)

A schedule is a **versioned, ordered sequence of activities anchored to an operating date**:
passenger trips, non-revenue movements, charging and layovers, with day offsets so a cycle can
cross midnight and run into Day 2 or later. Published versions are immutable; revisions create new versions.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2, Pydantic 2, SQLite (portable to PostgreSQL) |
| Migrations | `app/migrate.py` - additive, runs on every start (same approach as sunlease-hrms1) |
| Frontend | React 19, Vite, Tailwind 3, React Router, Axios, Lucide (plain JS/JSX) |
| Auth | JWT, local users, roles `VIEWER` < `SCHEDULER` < `PUBLISHER` < `ADMIN` |
| Deploy | Docker (multi-stage), `./data` volume, port **8030** |

## Run it

### Docker

```bash
cp .env.example .env            # set DEPOT_SECRET_KEY (openssl rand -hex 32)
docker compose up -d --build    # http://localhost:8030
```

The first start creates the default logins. To load the sample data as well (a route with
both directions, a bus, staff, and a published 2-day cycle), run this once:

```bash
docker compose exec app python -m app.seed --publish
```

### Local development

```bash
# backend (API on :8030)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed --publish        # users + sample data (skip --publish to leave SCH-101 as a draft)
uvicorn app.main:app --reload --port 8030

# frontend (Vite on :5173, talks to :8030)
cd frontend
npm install
VITE_API_URL=http://localhost:8030 npm run dev
```

Or run `./startup.sh` to build the frontend and serve everything on :8030.

Default logins (change them after first login, under **Users**):

| User | Password | Access |
|---|---|---|
| admin | Admin@123 | Super admin (all companies and cost centers; manages organisation and users) |
| publisher | Publisher@123 | Publisher in cost center DEFAULT (can publish/unpublish/retire) |
| scheduler | Scheduler@123 | Scheduler in DEFAULT (masters + drafts) |
| viewer | Viewer@123 | Viewer in DEFAULT |

### Trip sheets (Part 2, phase A)

- **Clone a schedule**: the copy icon on a schedule row copies its runs, crew pattern and shifts onto another bus as
  a **draft** at version 1 (the version in force on the date you give is the one copied). Nothing is published - the
  draft is validated and published like any other, so a second bus on the same pattern is set up by editing rather
  than re-typing.
- **Trip sheets** board: pick a date to see every bus with a published schedule that day; *Start sheet* lays the sheet
  out from the exact published version that applied (the sheet keeps that version for good).
- Clerks (role **MIS / Clerk**) type the driver's paper sheet: status per run (operated / cut short / cancelled),
  departed/arrived times, odometer start/end per run (and per stop when the paper has it), SOC, charging kWh. The wand
  button fills a run that ran to plan. Unplanned runs can be added as *extra runs* (billed only when marked payable).
- **Billing** = planned km, minus km lost to cancelled or cut-short runs (cut short = billed up to the last stop
  reached). Each loss records a reason and who it is **attributable to** (operator / client / external); each cost
  center chooses which attributions are still billed (default: client).
- **Crew** follows the schedule version's crew pattern (one driver for the day, or shifts; conductor optional). A
  *Change* records a mid-duty handover: the outgoing duty ends at that time and the replacement takes over.
- Workflow: Draft -> Submitted (clerk) -> Approved (publisher; locked, also at database level). Admins can reopen an
  approved sheet with a reason. A version used by trip sheets cannot be unpublished, and a new version must start
  after the last trip-sheet date.

### Trip sheets (phase B): print and reports

- **Printed sheets (A4 portrait)**: on the Trip sheets board, the printer icon prints one bus's sheet;
  *Print all sheets* prints every bus for the date (print at 100%, not "fit to page"). The layout follows the
  depot's own paper form: **From** and **To** printed per run (English with the regional name under it, and the
  run's trip number, planned window and km), then everything about the departure together - **Departed, Start SOC,
  Odo start** - and everything about the arrival together - **Arrived, End SOC, Odo end** - then **Reason #** and
  **Stop #**. Those fields are **written freely into ruled cells**; the only character boxes left in the run table
  are the **Ran / Cut short / Not run** ticks. Times are asked for in 24-hour form, because a 12-hour time with no
  am/pm cannot be read back reliably.
- **Layovers, charging and halts are information only**: a single line showing what and when, so the driver sees
  the gap and the office knows why the SOC moved, with nothing to fill in. They are completed by *Fill in layovers
  and SOC* on the entry screen.
- **The crew block keeps character boxes** (employee number, duty times, driver change, bus change), since those
  are written once at the top rather than on every run.
- **Foot of the sheet**: Observations, Final run km / Dead km / Duty completed, the reason-code and stop legends,
  and four signatures - driver, conductor, station incharge, operator incharge.
- One page holds 20 runs with the footer; a longer day continues on further pages with the column headings and the
  ID line repeated (`DEPOT-TS S<schedule> V<version> <yyyymmdd> · bus`), which is how a scanned page is matched
  back to its sheet.
- **Undated (reusable) sheets**: tick *Undated (reusable)* before printing - the date in the header and in the ID line
  become boxes the driver fills in, so one printout serves every day while that schedule version is current. The
  sheet prints the version's validity ("v2 · from ... - discard if a newer version starts"). On entry, type the
  **Version on paper** (the V in the ID line); if it differs from the version that applies on that date, the sheet
  shows a warning.
- **Bus change**: the crew block has a row for a different bus that ran the schedule - registration in boxes (no
  spaces), the run number it took over from, and a reason number. On entry the registration is matched to a bus in
  the cost center (unknown registration = warning); odometer checks restart on the new bus from that run, and the
  next day's opening reading still follows the assigned bus's own runs. Billing shows the day as "EV-101 → EV-102".
- **Trip sheet language**: labels on the printed sheet are bilingual - English plus a regional language. It is chosen
  on the **company** (Organisation -> company -> *Trip sheet language*), and a **cost center** may override it where
  that depot prints in another language (Telugu, Kannada, Tamil, Hindi, or English only). Translations are a first
  draft, have them checked by a native speaker before the sheets go to drivers.
- **Reason codes** (Masters -> Reason codes): each company configures its own fault reasons - code, English name,
  name in the regional language, and who the loss is **attributable to** (operator / client / external, which decides
  whether the km is still billed). Nine are seeded on first use (breakdown, accident, no crew, charging, traffic, road
  closure, weather, client instruction, other). The **No. on sheet** column is what the driver writes in the
  *Reason #* boxes; it never changes, so printed sheets stay readable. The footer legend prints each reason as
  `001 Vehicle breakdown (<regional name>)`. A reason already written on a sheet cannot be deleted, only deactivated.
### Reading scanned paper sheets

- **Upload scanned sheets** on the Trip sheets board takes scanned **PDFs** of the day's paper sheets - the whole
  depot in one file, one file per bus, or any mix: **several files can be picked at once**, and each becomes its own
  upload. Scan at 200-300 dpi, grayscale; up to 40 MB a file.
- **One bus at a time**: each row of the board has its own upload button, for the paper of that bus alone. A page
  that turns out to be another bus, or another day, is **rejected** - nothing is written, and the error names both
  buses ("this page is EV-101 (SCH-101), but it was uploaded against EV-102 (SCH-102) - nothing was changed").
  The whole-day button accepts any bus of the cost center, which is the point of it.
- **Looking through what was uploaded**: after an upload, and from *Look through all pages* on the uploads list, the
  documents open one page at a time - the scanned paper on the left, what was read from it on the right, with the
  issues and a link to the trip sheet. Previous / Next (or the arrow keys) step through every page of every file.
- Reading happens on this server, offline (pypdfium2 + OpenCV + Tesseract); nothing is sent anywhere.
  The reader straightens the page, finds the printed boxes, identifies the sheet from the ID line
  (`DEPOT-TS S<schedule> V<version> <date>`, or the handwritten date boxes on an undated sheet), and maps the box
  rows onto that version's runs. Nothing about a schedule is hardcoded, so any sheet this app prints can be read,
  of any length; a long day spanning two pages carries on across them.
- What it writes: status tick (Ran / Cut / Not), departed and arrived with the +day box, odometer start and end,
  start and end SOC, reason number and stop number. Then it runs **Fill in layovers & SOC** and validation.
- **Sheets always stop at Draft** - a person reviews and submits. A sheet already submitted or approved is never
  touched; the page is reported as skipped.
- **A new upload for the same day replaces the one before it** and re-reads the sheets it covers (the earlier upload
  is kept, marked superseded). Re-scanning a corrected batch is the normal way to fix a bad scan; *Read again*
  re-reads the same file, for instance after a reason code was corrected.
- **Nothing is guessed.** An empty box is read as empty. Only ink that cannot be made out is reported, as a warning
  naming the one run and field - "#3 Non Revenue Movement: odo end could not be read - enter it by hand". Those
  appear on the trip sheet screen for the clerk to key in, and the sheet is then validated again as usual. A page
  whose ID line cannot be read, or that belongs to another cost center, is reported and left alone.
- The daily board shows a symbol per bus from its last validation (error / warning / clean) and marks sheets that
  came from a scan.
- **The paper is attached to its trip sheet**: the entry screen shows the scanned page(s) it was read from, as
  thumbnails that open full size, beside the list of fields still to key in. A day that ran over two pages shows
  both. Page images are served through the API (bearer token), so they are fetched like any other call rather than
  with a plain image URL.

### Reports

- **Reports → Billing**: approved sheets only, in km - planned billable km, lost km by attribution
  (operator / client / external), lost km still billed, deducted km, billable km, odometer km and deviation, per
  schedule with day drill-down. Excel export (Summary / Daily / Losses) for publishers and above.
- **Reports → Missing sheets**: bus-days with a published schedule whose sheet is not started, draft or submitted.
- **Reports → Crew hours**: duty time per employee from trip sheets (cut short by driver changes), double bookings
  flagged; Excel export.

### Companies, cost centers and roles

- A **company** has one or more **cost centers** (e.g. a depot or contract). Buses, routes, schedules, staff and
  validation settings belong to a cost center; **locations** belong to the company and are shared by its cost centers.
- A user has a **role per cost center** (Viewer < MIS / Clerk < Scheduler < Publisher < Admin) and switches cost center in the top bar.
  **All my cost centers** combines them for viewing; new records need a specific cost center, and a record opened from
  the combined view is edited under the user's role in that record's own cost center.
- Only the **super admin** creates companies, cost centers and users (**Organisation**, **Users**). Cost-center Admins
  change that cost center's validation settings and see its audit log.
- The API takes the working cost center in the `X-Cost-Center-Id` header (`all` for the combined view). Records of
  cost centers the user has no role in are reported as not found.
- Upgrading a single-tenant database moves all existing data into company **SUNLEASE / Sunlease Renewables**, cost
  center **DEFAULT**; `admin` becomes the super admin and other users keep their role in DEFAULT.
- Codes (fleet, registration, location, route, schedule) are unique across the whole system, not per company.

To reset the dev database, stop the server, delete `data/depot.db` and run `python -m app.seed --publish`.

## Tests

```bash
cd backend && source .venv/bin/activate && python -m pytest app/tests -q   # 75 API/engine tests (1 skipped without tesseract)
cd frontend && npm test                                                    # date/time parsing tests
```

The backend tests cover:
- route directions with different distances
- stop times, including midnight crossings and Day 2/3 trips
- charging rules and movement payability
- overlaps, gaps and continuity
- SOC rules (schedules carry planned km only, no odometer readings)
- steering time (passenger trips + non-revenue movements)
- configurable mandatory readings
- versioning and supersession
- immutability, at both the API and the database-trigger level
- bus conflicts across schedules and shifted days
- roles, and employee stints with Excel import

## How it works

- **Time:** every activity stores a local `HH:MM` and a `day_offset` from the operating date. Timestamps
  are derived from (operating date + offset + time + timezone, default `Asia/Kolkata`). Durations are
  never computed from clock times alone.
- **Validation:** the backend runs [schedule_service.py](backend/app/services/schedule_service.py). Errors block
  publishing, and warnings need an explicit acknowledgement. The checks are:
  - terminals and direction membership, stop order, and required stop times
  - chronology across midnight
  - distance reconciliation within a tolerance
  - SOC range and (optionally) required SOC
  - charging-capable locations, and stationary charging and layovers
  - overlaps, gaps and location jumps
  - version date conflicts
  - bus conflicts
- **Bus conflicts:** each daily occurrence is expanded to an absolute interval. A cycle longer than 24h
  is rejected because it would collide with its own next occurrence. Overlaps with other published
  schedules on the same bus are checked across shifted days, so an evening cycle running into another
  schedule's next morning is caught.
- **Versioning:** a new version starts as a copy of the latest published one. Publishing it closes the
  previous version the day before (status `SUPERSEDED`). Historical dates still resolve to the version
  that applied (`GET /api/schedules/{id}/timeline?date=`).
- **Immutability:** service-layer checks plus SQLite triggers (installed by `migrate.py`) reject any
  insert, update or delete of activities, trips, stop times, movements, charging and layovers whose
  version is not `DRAFT`.
- **Part 2 readiness:** future trip sheets can reference `schedule_id`, `schedule_version_id`,
  operating date, `activity_id`, `trip_number` and `scheduled_stop_time_id`. Planned rows are never edited
  after publishing.

## Employees (roster groundwork)

One row per employment stint (`employee_number` + `start_date`). The end date is the inclusive last
working day, and stints cannot overlap. A rejoiner gets a new row. There are two ways to load employees:

- **Excel upload:** download the template from the Employees page. Dates can be `DD-MMM-YYYY` or ISO.
  The upload is all-or-nothing: one bad row and nothing is saved.
- **HRMS sync:** set `DEPOT_HRMS_SYNC_URL` (and `DEPOT_HRMS_SYNC_TOKEN`). The app GETs that URL and expects
  a JSON list of objects like this:
  ```json
  {"employee_number": "D001", "full_name": "...", "designation": "Driver", "staff_type": "DRIVER",
   "home_depot_code": "DEP01", "start_date": "2025-04-01", "end_date": null, "status": "ACTIVE"}
  ```
  `staff_type` is `DRIVER`, `CONDUCTOR` or `DEPOT_STAFF`. One object per employment episode.
  sunlease-hrms1 does not expose this endpoint yet. It needs a small read-only export route
  (not built; it changes the HRMS project).

## Keyboard-first data entry

Press `?` anywhere for the shortcut list.

| Key | Action |
|---|---|
| Enter / Shift+Enter | Next / previous field; Enter on the last field saves (or adds a row in grids) |
| Ctrl+S, Esc | Save, cancel |
| ↑ ↓ | Move between grid rows; step through dropdown options |
| Dates | `21-Oct-2026`, `211026`, `21102026`, `21-oct`, `21`, `T` (today), `+1` / `-1` |
| Times | `930` → 09:30, `2230` → 22:30; in an activity time, `+` / `-` changes the day offset |
| Schedule builder | Alt+T trip · Alt+M movement · Alt+C charging · Alt+L layover · Alt+V validate · Alt+P publish · Alt+Enter save & add next · Alt+↑/↓ reorder · Delete remove |

Each new activity starts where the previous one ended (same location, same time and day). In a stop
timetable, pressing Enter on an empty time takes the previous stop's departure.

## API

REST endpoints under `/api` follow spec §8:
- `/vehicles`, `/locations`, `/routes`, `/routes/{id}/directions`, `/directions/{id}/stops`
- `/schedules`, `/schedules/{id}/versions`, `/schedule-versions/{id}`
- `.../activities` and `.../activities/reorder`
- `.../validate`, `.../publish`, `.../timeline`, `.../print`

There are also `/employees`, `/employees-import`, `/employees-sync-hrms`, `/settings`, `/users` and `/audit-logs`.
Interactive docs are at `/docs`.
