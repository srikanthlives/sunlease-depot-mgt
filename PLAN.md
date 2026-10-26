# Sunlease Depot Management — Build Plan

Source spec: `sunlease_fixed_bus_schedule_specification.md` (authoritative for the
schedule module). This file records the decisions made before coding and the build order.

## Decisions

| Area | Decision |
|---|---|
| App | Standalone app in `sunlease-depomgt`, modelled on `sunlease-hrms1` |
| Backend | FastAPI, SQLAlchemy 2, Pydantic 2, SQLite (portable to PostgreSQL) |
| Migrations | HRMS-style additive `migrate.py`, run on every start (not Alembic) |
| Frontend | React 19, Vite, Tailwind 3, React Router, Axios, Lucide, plain JS/JSX |
| Auth | JWT login, local users, 3 roles: `VIEWER`, `SCHEDULER` (edit drafts), `PUBLISHER` (publish) + seeded admin |
| Deployment | Multi-stage Dockerfile, docker-compose, `./data` volume, `startup.sh`, env prefix `DEPOT_*` |
| Release 1 scope | Bus schedule module exactly as in the spec |
| Deferred | Crew assignment to activities, shifts/attendance/leave, Part 2 actual trip sheets (schema leaves room) |
| Audit | Append-only `AuditLog` for create/update/publish actions, written via an audit service |
| Deletes | No hard delete of anything referenced by published schedules; deactivate instead |

## Employee data (roster groundwork)

- `Employee` mirror table: one row **per employment stint** (rejoiners get a new row).
  Fields: `employee_number`, name, designation, `staff_type` (DRIVER / CONDUCTOR / DEPOT_STAFF),
  home depot (Location), `start_date` (required), `end_date` (optional, **inclusive** last day),
  status, `source` (UPLOAD / HRMS), `last_synced_at`.
- Unique key `(employee_number, start_date)`; overlapping stints for the same employee rejected.
- Available on date D iff `start_date <= D` and (`end_date` is null or `D <= end_date`).
- Loaded two ways, both upserting: **Excel upload** (downloadable template) and
  **HRMS sync** (pull from a read-only HRMS export endpoint; configured via env, needs a small
  endpoint added to `sunlease-hrms1` when approved).
- Later phases: crew assignment is rejected outside employee dates; end dates inside a
  schedule's validity window raise warnings; pickers list only available staff.

## UI requirements (apply to every form)

**Keyboard-first data entry**
- Tab order follows visual order; icon buttons inside grids are `tabIndex=-1`.
- Enter = next field, Shift+Enter = previous; Enter on last cell of a grid row saves and adds a row.
- Autofocus first field; Esc cancels; Ctrl+S saves; first invalid field focused on submit.
- Spreadsheet-like activity grid and stop timetable (Tab across, arrows between rows).
- Type-ahead comboboxes for location/route/vehicle/employee. Number inputs: no spinners, select on focus.
- `?` opens a shortcut help overlay.

**Dates and times**
- Dates displayed and typed as `DD-MMM-YYYY` (e.g. `21-Oct-2026`). Accepts `21102026`, `211026`,
  `21-10-2026`, `21-oct`, `21`, `T` (today), `+1`/`-1`. API and DB store ISO dates.
- Times are 24-hour `HH:MM`; `930` -> `09:30`. Each activity time has a day-offset (`+0`, `+1`…).
  End < start with no offset suggests +1 rather than assuming it. Live duration from full timestamps.
- Stop times default to previous stop's departure.

**Infographics (inline SVG + Tailwind, no chart lib)**
- Route: proportional line diagram per direction (upstream above downstream), live preview in builder,
  flagged bad terminals / zero-distance segments.
- Schedule: Gantt-style day timeline coloured by activity type, midnight and Day 2/3 separators,
  overlap (red hatch) and gap (dashed) markers, payability badges.
- SOC profile (gaps where readings missing, never invented), summary tiles
  (total km, revenue vs non-revenue, trips, charging h, layover h), timetable grid,
  bus-conflict view at publish, vehicle assigned/free badges. All print cleanly.

## Build order

1. **Skeleton** — repo layout, Docker, `startup.sh`, config, DB session, auth + roles, audit log, tests harness, frontend shell with login.
2. **Masters** — Vehicle, Location, Route, RouteDirection, RouteStop (+ route diagram), Employee mirror + Excel upload + HRMS sync; shared keyboard-first input components.
3. **Schedule engine** — BusSchedule, ScheduleVersion, ScheduledActivity (+ Trip/StopTime/Movement/Charging/Layover), day-offset timestamps, validation, publish, bus-conflict checks, immutability; tests at each step.
4. **Schedule UI** — builder grid, stop timetable, validation/publish screen, viewer, print view, infographics.
5. **Seed data and README** — sample data, setup instructions.

## Status (21-Oct-2026)

Steps 1-5 built. 27 backend tests + frontend date/time tests pass; keyboard-only entry verified in a
headless browser (bus, schedule, movement, trip with stop timetable, layover, validation).

Deviations from the plan:
- No planned odometer readings (decided 21-Oct-2026): a recurring schedule cannot know the bus's odometer, so schedules carry
  planned km only; trip sheets will compare actual km against them. The odometer columns are dropped by migrate.py.
- Summary tiles include steering time (passenger trips + non-revenue movements).
- **Multi-tenancy** (added 21-Oct-2026, modelled on sunlease-hrms1 but with roles per cost center): Company -> Cost
  Center; `UserCostCenterRole` holds a role per cost center; `User.role` is SUPER_ADMIN or USER. Scoping lives in
  `core/access.py` (header `X-Cost-Center-Id`, `all` = combined read view). Locations are company-level.
- **Trip sheets phase A** (21-Oct-2026): board, entry from the paper sheet, billing = planned km minus lost km
  (attribution decides), crew pattern on the version + mid-duty handover, MIS / Clerk role, submit/approve/reopen,
  approved-sheet DB locks, version safeguards.
- **Trip sheets phase B** (21-Oct-2026): bilingual printed sheet (per-cost-center print language), billing report
  (approved only, km only) + Excel, missing-sheets report, crew-hours report (no duty-hour limit, per user).
- **Printed sheet refinements** (22-Oct-2026): OCR boxes on A4 portrait, +day box on arrival, regional location names,
  sheet no. replaced by the ID line on every page, undated reusable sheets with version-on-paper warning, bus change
  (registration in boxes, from run, reason). Demo schedules MAX-1PAGE (20 runs = 1 page) and MAX-2PAGE (48 runs = 2
  pages) check the fit, dated and undated.
- **Configurable reason codes** (22-Oct-2026): Masters -> Reason codes (per company, scheduler+), regional name per
  reason, delete only when unused, printed legend shows English with the regional name in brackets.
- **Scanned sheet intake** (22-Oct-2026): upload a scanned PDF (day or single bus), offline reading with
  pypdfium2 + OpenCV + Tesseract, pages matched by the printed ID line, box rows mapped to the version's runs,
  layover/SOC fill and validation after reading, drafts only, re-upload supersedes and re-reads, per-field
  warnings shown on the entry screen. Docker image carries tesseract-ocr.
- Extra activity type **Halt** (not in the spec): one undivided off-service block at a depot or night-halt terminal
  (parking, washing, charging, maintenance are not timed separately). SOC may rise or fall. Halt time is left out of the
  cycle time but still counts for bus conflicts and the 24-hour limit.
- HRMS export endpoint in sunlease-hrms1 not built (needs approval to change that project); the sync client
  and its JSON contract are ready (see README).
- Docker publishes on port 8030 (8000 is used by another local app; HRMS uses 8020).

Next phases: crew assignment to published activities (using employee stint dates), Part 2 trip sheets.

## Definition of done

As in spec §13: configure route, assign to physical bus, build multi-activity recurring schedule,
validate and publish, view chronological timetable across calendar dates, revise via new immutable
version; all persisted and enforced by the backend; automated tests pass.

## Next module — Duty roster (decided 25-Oct-2026)

Forward-planning counterpart to trip sheets: today crew is named only *after* the day, on
`TripSheetCrew`. The roster names crew *before* the day, is frozen once created, and is compared
against what actually happened.

### Decisions

| Area | Decision |
|---|---|
| Entry | Pattern generates, grid edits. A duty pattern (rotating cycle) produces a draft; the date x schedule grid is the editing surface |
| Freeze | A roster is immutable once published. A change (new schedule, new employee, correction) creates a **new version covering the whole period**: days already completed are copied across unchanged and stay locked, so only days from the change onward can differ. The prior version is superseded, never edited |
| Current version | Exactly one version is live at a time — the latest. The grid, entry and actuals all read it; earlier versions are kept only to diff v1 -> v2. No period is ever assembled from two versions |
| Absence | `EmployeeAvailability` register: per employee and date range, `ON_DUTY` / `WEEKLY_OFF` / `LEAVE` / `TRAINING` / `SICK` / `OTHER`. A depot-level marker, not HRMS leave approval |
| Actuals | A **separate** day-by-day actual roster (`DutyActual`), entered by hand, tracked against the current version only. A new version does not restart or re-snapshot actuals already recorded. The plan is never mutated by what happened |
| Comparison | Two comparisons: planned vs actual per day (the operational one), and version vs version (what the revision changed) |
| Roles | `SCHEDULER` edits drafts, `PUBLISHER` publishes/freezes, `MIS` records actuals, `VIEWER` reads |

### Model

- `DutyRoster` — header per cost center: `roster_code`, period (`period_from`, `period_to`), status.
- `DutyRosterVersion` — immutable, versioned, published copy of the **entire period**, with
  `version_number`, `status`, `published_at/by`, `change_reason`, `superseded_by_version_id`,
  `prior_status` (the `ScheduleVersion` publish / unpublish bookkeeping, reused). No `valid_from` /
  `valid_to`: a version covers the roster's whole period, and the latest published one is the only
  live one. Creating version N+1 copies every assignment from N, including completed days, which are
  marked locked and rejected for edit (`locked_through` on the roster = the last closed day).
- `DutyPattern`, `DutyPatternSlot`, `DutyPatternMember` — a cycle of `cycle_days` days; each slot is
  (cycle day, schedule, shift or crew role) or an off day; ordered members rotate through the slots.
- `DutyAssignment` — the planned duty: `(roster_version_id, duty_date, schedule_id, shift_id,
  crew_role) -> employee_id`, plus `source` (`GENERATED` / `MANUAL`) and remarks. Unique on that key.
  `shift_id` is null for a `SINGLE` crew-mode version.
- `DutyActual` — one row per real duty, keyed on `(roster_id, duty_date, schedule_id, shift_id,
  crew_role)` — the **roster**, not a version, so a new version never orphans or duplicates what was
  already recorded. Holds `planned_employee_id` (copied from the plan when the day is opened),
  `actual_employee_id` (null = nobody worked it), `status` (`AS_PLANNED` / `REPLACED` / `ABSENT` /
  `NOT_OPERATED`), `reason_id` (reuses `TripReason`), `recorded_by`, `recorded_at`, and
  `roster_version_id` recording which version was live when it was recorded. Closing a day locks its
  rows and advances the roster's `locked_through`.

### Validation (reuses `trip_sheet_service._validate_crew` rules)

- Employee stint dates: assignment rejected outside `start_date` .. `end_date`; an `end_date` inside
  the roster period is a warning.
- `staff_type` must match `crew_role`; conductor slots only where `conductor_required`.
- No double booking: one employee on two schedules on the same date with overlapping duty spans.
- Availability register conflict (`LEAVE` / `WEEKLY_OFF` / …) is a warning, overridable with a remark.
- Every crew slot of every schedule operating on the date must be filled before publish.
- The schedule must have a published version covering the date; slots come from that version's
  `crew_mode` / `ScheduleShift` rows.

### Trip sheet link

Creating a sheet pre-fills `TripSheetCrew` from the **actual** roster for the date when the day is
open, otherwise from the plan. The sheet records that its crew diverges from the roster, so the
divergence is visible in the comparison without the clerk entering it twice.

### Reports

- End-of-day duty summary: per schedule, planned vs actual crew, counts of replaced / absent /
  uncovered slots.
- Period statistics: per employee, duties planned vs operated, replacements made and received,
  absence rate, schedules worked, hours (from the existing `crew_hours` report); Excel export.
- Side-by-side planned/actual comparison screen with the day's changes and reasons.

### Build order

1. ~~Models + additive `migrate.py` tables; `EmployeeAvailability` register with CRUD and UI.~~ **Done 25-Oct-2026** (8 tables, 2 lock triggers, `availability_service`, Masters -> Availability, 5 tests).
2. ~~`roster_service.py`: draft roster, manual grid assignments, validation.~~ **Done 25-Oct-2026** (slots read from `version_for_date`, grid + copy-days + repeat-block + validate endpoints, crew dropdown from `crew-options`, keyboard grid at Operations -> Duty roster, 11 tests).
   - **Spares and shunting** (`duty_extras`): duties with no bus, any number per day, added from the grid's `+` per date. Shunting may carry start/end times. An empty row warns; a spare who also drives a bus that day warns rather than errors, because depots do call spares in.
   - **Repeat block**: the first week (or any block) copied forward to the end of the period, last block cut short. The workhorse for a monthly roster.
   - A draft is editable on **every** date of the period, past days included, until it is published. A grey cell means the schedule does not run that day (its `effective_from` / `effective_to` decide), which is not the same as a gap.
   - **Cost center**: crew may only be rostered onto buses of their own cost center. Enforced at save on roster assignments, spares, trip sheet crew and the availability register. An employee entered against the wrong depot is moved (unused) or transferred as a new stint (used), via `POST /employees/{id}/transfer`.
3. ~~Duty pattern + generator, with hand edits on top (`source` flag preserved).~~ **Done 25-Oct-2026**. A pattern is a rotation: one duty (or an off day) per cycle day, and an ordered line of crew, each starting the cycle a day further along. One duty per cycle day and a line no longer than the cycle, so the rotation cannot double-book. Masters -> Duty patterns; `Generate` on the draft.
4. ~~Publish / freeze / new version / unpublish, mirroring `schedule_service`.~~ **Done 25-Oct-2026**. `roster_publish_service`: errors block publishing, warnings must be confirmed; a revision copies the whole period into a new draft (closed days marked `CARRIED` and still locked); unpublish is refused once a day is closed or an actual recorded. A draft roster can be deleted, a published one cannot.
5. ~~`DutyActual`: open a day, record replacements and absences, close and lock.~~ **Done 25-Oct-2026**. `duty_actual_service`: opening a day snapshots the live plan (re-runnable, adds new slots only); the status is derived from who worked it, and any change from plan needs a reason or remark; closing advances `locked_through`. **Reopen** is allowed to a PUBLISHER with a reason (the same escape hatch trip sheets have) and unlocks every later day, since the lock is one watermark.
6. ~~Trip sheet pre-fill from roster + divergence flag.~~ **Done 25-Oct-2026**. Creating a sheet fills its crew from the roster - the recorded actuals when the day is open, the plan otherwise - and a sheet whose crew differs from the roster raises `CREW_OFF_ROSTER` as a warning.
7. ~~Day comparison screen, end-of-day summary, period statistics + Excel.~~ **Done 25-Oct-2026**. Operations -> Duty day (plan beside actual, day strip, open/close/reopen) and Reports -> Duty statistics (planned, worked, stood in, missed, spare, shunting per employee), both with Excel.
8. ~~Version diff view: v1 vs v2, changed slots only, completed days shown as carried over.~~ **Done 25-Oct-2026**. `Compare versions` on the roster screen; bus duties and spares listed separately.

### Mid-duty handover and spares (26-Oct-2026)

A duty's actuals are **segments**: `DutyActual` can hold several rows for one planned slot, split the
way a trip sheet's crew change is (`replaces_actual_id` plus the hours each person held). Statuses
`HANDED_OVER` and `TOOK_OVER` join the original four. The planned employee stays on every segment, so
the duty still belongs to them for reporting.

The three spare cases the depot described:

1. **Standby, never called** — the spare's own `SPARE` row stays `AS_PLANNED`. The day view says
   "called out to <bus>" only when they were actually used.
2. **Covers a whole duty** — the bus slot is `REPLACED`. `ACTUAL_ALSO_SPARE` is suppressed when the
   second duty is one they covered: being called out is the job, not an anomaly.
3. **Takes over part-way** — a handover at a time, needing a `TripReason` code or a remark
   (decided 26-Oct-2026), recorded by `MIS` (decided 26-Oct-2026). Chains for a second takeover;
   `undo` removes the last segment and restores the previous holder.

Clashes are checked **per segment**, not per whole duty, so a spare who stood by and took over at
11:20 is fine while somebody already driving across that stretch is an error. `SEGMENT_GAP` and
`SEGMENT_OVERLAP` catch segments that do not meet. Hours are derived from the plan for rows recorded
before they were stored, so an older day needs no backfill. Statistics gained an **Hours** column, so
a handed-over duty counts as the part each person worked rather than a whole duty each.

**Migrations that change a table's shape**: `migrate.py` has `_rebuild_with_rows` for a changed
UNIQUE constraint, which SQLite cannot ALTER. It runs in one transaction, resumes a run that died
part-way (the stash `<table>__old` is found and finished), carries model defaults into new NOT NULL
columns, and verifies row counts before dropping the stash. Tests in `test_migrate.py`. This exists
because the first attempt stranded 11 rows in the stash and left the live table empty: never rebuild
a table without carrying its rows, in one transaction, verified.

### Plan against actual, on the one grid (26-Oct-2026)

`GET /rosters/{id}/grid?actuals=true` lays what was recorded over the plan: each cell keeps its
planned employee and gains `recorded`, `actual_status` and `actual` — one entry per segment, so a
duty handed over part-way carries both names and the time of the change. Spares and shunting rows
get the same treatment. The actuals are only queried when asked for, so the plan grid used for data
entry stays as cheap as it was.

The screen is the same grid under a **Plan / Plan vs actual** toggle, not a separate page. In the
overlay the planned name sits above the actual, struck through when they differ, and the cell is
tinted: plain as planned, blue replaced, amber handed over, red nobody, grey not operated, pale
dashed not recorded. A day nobody opened shows the plan and says "not recorded" rather than looking
like agreement. The overlay is read-only — what happened is recorded on Duty day, and a published
plan is frozen anyway.

### Trip sheet crew against the roster (26-Oct-2026)

`roster_crew_check` compares a sheet's crew with the duty roster for that bus and date (the recorded
actuals once the day is open, the plan otherwise). The trip sheet board shows an amber mark naming
both drivers, the sheet's own Crew card shows a band with the detail, and sheet validation keeps
raising `CREW_OFF_ROSTER` from the same comparison. A name is a match when it is **anybody** the
roster had on that slot, because a handed-over duty was held by two people and either may appear on
the paper.
