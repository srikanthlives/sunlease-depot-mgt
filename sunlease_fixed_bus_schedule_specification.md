# Sunlease Fixed Bus Schedule Management Module
## Software Requirements and Implementation Specification

## 1. Product objective

Build a web-based module to define, validate, publish, view, and revise the planned operating cycle of an electric bus assigned to a fixed recurring schedule.

A schedule is a **chronologically ordered sequence of activities**, not merely a list of passenger trips. It may include:

- Depot-to-terminal positioning movements.
- Passenger trips in either route direction.
- Intermediate stops with scheduled arrival and departure times.
- Layovers and overnight parking.
- Movements to and from charging locations.
- Charging sessions.
- Final movements to a depot, terminal, charging point, or another designated location.
- Activities that continue across midnight or into Day 2, Day 3, or later.

The schedule must be manually configurable and repeat according to its recurrence rule. Daily recurrence is the default for the first release.

### Scope

- **Part 1 — Fixed Schedule Management:** Configure, validate, publish, and revise recurring planned bus schedules.
- **Part 2 — Actual Trip Sheets:** Future integration for actual departure/arrival times, odometer, SOC, charging, and deviations. Do not build the complete Part 2 module in this release.

## 2. Recommended technology stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS |
| Routing | React Router |
| API | Python FastAPI |
| Database | SQLite initially |
| ORM and migrations | SQLAlchemy and Alembic |
| Validation | Pydantic |
| UI icons | Lucide React |
| Date/time handling | Python `datetime`, timezone-aware timestamps, browser date/time inputs |

Keep the database and business logic portable to PostgreSQL if the system later needs multiple concurrent depot users or higher operational volume.

## 3. Core business rules

1. Each schedule is assigned to one physical bus.
2. A schedule can contain any number of ordered activities.
3. A passenger trip references a route and a specific route direction.
4. Each direction has its own stop sequence and distance values.
5. Every passenger stop can have planned arrival time, departure time, odometer, and SOC.
6. Every non-passenger movement has a purpose and an independently configurable payability status.
7. Charging is a stationary activity; movements to and from the charger are separate activities.
8. Layovers are explicit activities at a defined location.
9. Schedule end location is configurable. It does not have to be the depot.
10. A schedule may cross midnight or extend across several calendar days.
11. Daily recurrence does not mean that the schedule must finish on the same calendar day.
12. Published schedules must be versioned and preserved for historical reporting.
13. Part 2 must reference the exact published schedule version used for the operating date.

## 4. Data model and database tables

Use the following relational database structure. Use primary keys, foreign keys, indexes, validation constraints, and audit fields wherever appropriate.

### 4.1 `Vehicle`

Stores the physical bus master.

| Field | Type / rule |
|---|---|
| `vehicle_id` | Primary key |
| `fleet_number` | Required, unique |
| `registration_number` | Required, unique |
| `battery_capacity_kwh` | Optional positive decimal |
| `home_depot_id` | Foreign key to `Location`, nullable if not assigned |
| `status` | Active, inactive, retired |
| `created_at`, `updated_at` | Audit timestamps |

A schedule must reference a physical vehicle, not just a vehicle category.

### 4.2 `Location`

Stores depots, terminals, bus stops, charging sites, and other locations.

| Field | Type / rule |
|---|---|
| `location_id` | Primary key |
| `location_code` | Required, unique |
| `location_name` | Required |
| `location_type` | Depot, terminal, bus stop, charging point, other |
| `supports_charging` | Boolean |
| `latitude`, `longitude` | Optional |
| `is_active` | Boolean |
| `created_at`, `updated_at` | Audit timestamps |

A physical location should have one master record even if it functions as both a depot and a charging site. Use capabilities or related records if more detailed facility modelling is needed later.

### 4.3 `Route`

Stores the service or route identity.

| Field | Type / rule |
|---|---|
| `route_id` | Primary key |
| `route_code` | Required, unique |
| `route_name` | Required |
| `description` | Optional |
| `status` | Active, inactive |

Do not store the start and end terminal only at the route level, because the terminals change when travelling in the reverse direction.

### 4.4 `RouteDirection`

Stores the direction-specific route definition.

| Field | Type / rule |
|---|---|
| `direction_id` | Primary key |
| `route_id` | Foreign key to `Route` |
| `direction_code` | Example: `UPSTREAM`, `DOWNSTREAM` |
| `direction_name` | Display name |
| `start_terminal_id` | Foreign key to `Location` |
| `end_terminal_id` | Foreign key to `Location` |
| `total_distance_km` | Calculated or verified total |
| `is_active` | Boolean |

A route can have multiple directions. For the initial release, create upstream and downstream directions as needed.

### 4.5 `RouteStop`

Stores the ordered stops and route distances for each direction.

| Field | Type / rule |
|---|---|
| `route_stop_id` | Primary key |
| `direction_id` | Foreign key to `RouteDirection` |
| `stop_sequence` | Positive integer |
| `location_id` | Foreign key to `Location` |
| `distance_from_previous_km` | Non-negative decimal |
| `cumulative_distance_km` | Non-negative decimal |
| `is_pickup_dropoff_stop` | Boolean, default true |

Constraints:

- `stop_sequence` must be unique within a direction.
- The first stop must match the direction's start terminal.
- The last stop must match its end terminal.
- Cumulative distance must equal the running total of distances from previous stops.
- The reverse direction must have its own stop records and distance values, even if the physical stops are the same.

### 4.6 `BusSchedule`

Stores the recurring schedule identity and fixed bus assignment.

| Field | Type / rule |
|---|---|
| `schedule_id` | Primary key |
| `schedule_code` | Required, unique |
| `schedule_name` | Required |
| `vehicle_id` | Foreign key to `Vehicle` |
| `recurrence_type` | Daily in the initial release |
| `effective_from` | Required date |
| `effective_to` | Optional end date |
| `timezone` | Default `Asia/Kolkata` |
| `status` | Draft, published, retired |
| `created_by`, `created_at` | Audit |
| `updated_by`, `updated_at` | Audit |

One schedule represents a recurring operating pattern assigned to one physical bus. Schedule versions store changes to that pattern.

### 4.7 `ScheduleVersion`

Stores an immutable published version of a schedule.

| Field | Type / rule |
|---|---|
| `schedule_version_id` | Primary key |
| `schedule_id` | Foreign key to `BusSchedule` |
| `version_number` | Incrementing integer |
| `valid_from` | Required date |
| `valid_to` | Optional date |
| `status` | Draft, published, superseded |
| `published_at` | Nullable timestamp |
| `published_by` | Nullable user ID |
| `change_reason` | Optional text |

Rules:

- A draft version can be edited.
- A published version cannot be edited or deleted through normal application workflows.
- To change a published schedule, create a new version.
- Preserve old versions so historical trip sheets can reference the original plan.
- Prevent overlapping published versions for the same schedule.
- Prevent conflicting published operating cycles for the same physical bus.

### 4.8 `ScheduledActivity`

This is the central table. Each row represents one activity in the chronological schedule.

| Field | Type / rule |
|---|---|
| `activity_id` | Primary key |
| `schedule_version_id` | Foreign key to `ScheduleVersion` |
| `sequence_number` | Required positive integer |
| `activity_type` | `PASSENGER_TRIP`, `NON_REVENUE_MOVEMENT`, `CHARGING`, `LAYOVER` |
| `origin_location_id` | Foreign key to `Location` |
| `destination_location_id` | Foreign key to `Location` |
| `start_day_offset` | Non-negative integer |
| `scheduled_start_time` | Local time |
| `end_day_offset` | Non-negative integer |
| `scheduled_end_time` | Local time |
| `remarks` | Optional text |

Use separate detail tables for activity-specific fields rather than adding every possible field to this table.

**Time handling:** `day_offset = 0` means the schedule's operating date; `1` means the following date; `2` means two days after the operating date. Derive full timestamps using the operating date, offset, local time, and schedule timezone.

The origin and destination may be the same for a stationary activity, such as charging or layover.

### 4.9 `ScheduledTrip`

Stores the passenger-trip details for a passenger activity.

| Field | Type / rule |
|---|---|
| `activity_id` | Primary key and foreign key to `ScheduledActivity` |
| `trip_number` | Required within the schedule version |
| `route_id` | Foreign key to `Route` |
| `direction_id` | Foreign key to `RouteDirection` |
| `planned_distance_km` | Positive decimal |
| `planned_start_odometer_km` | Optional decimal |
| `planned_end_odometer_km` | Optional decimal |
| `planned_start_soc_pct` | Optional decimal, 0–100 |
| `planned_end_soc_pct` | Optional decimal, 0–100 |

The selected direction must belong to the selected route. The trip's origin and destination must match the direction's terminals.

### 4.10 `ScheduledStopTime`

Stores the timetable and planned reference readings at each stop for a particular trip.

| Field | Type / rule |
|---|---|
| `scheduled_stop_time_id` | Primary key |
| `activity_id` | Foreign key to `ScheduledActivity` |
| `route_stop_id` | Foreign key to `RouteStop` |
| `stop_sequence` | Positive integer |
| `arrival_day_offset` | Non-negative integer, nullable for origin |
| `scheduled_arrival_time` | Local time, nullable for origin |
| `departure_day_offset` | Non-negative integer, nullable for destination |
| `scheduled_departure_time` | Local time, nullable for destination |
| `planned_odometer_km` | Optional decimal |
| `planned_soc_pct` | Optional decimal, 0–100 |

Validation rules:

- At least two stops per passenger trip.
- Stop sequence must follow the selected direction.
- The origin has a departure time; the destination has an arrival time.
- Intermediate stops normally have both arrival and departure times.
- Arrival and departure must be chronological across midnight.
- Planned odometer should be non-decreasing along a trip.
- Every stop must belong to the direction selected by its passenger trip.

### 4.11 `ScheduledMovement`

Stores non-passenger movements, such as positioning, charging access, and return-to-depot journeys.

| Field | Type / rule |
|---|---|
| `activity_id` | Primary key and foreign key to `ScheduledActivity` |
| `movement_purpose` | Depot positioning, charging access, return to service, return to depot, maintenance, other |
| `planned_distance_km` | Non-negative decimal |
| `planned_start_odometer_km` | Optional decimal |
| `planned_end_odometer_km` | Optional decimal |
| `planned_start_soc_pct` | Optional decimal, 0–100 |
| `planned_end_soc_pct` | Optional decimal, 0–100 |
| `payability_status` | Payable, non-payable, to be confirmed |
| `payment_basis` | Per kilometre, fixed amount, included in contract, other, unspecified |
| `remarks` | Optional text |

**Important:** `movement_purpose` and `payability_status` must be independent fields. A movement to a charging depot does not automatically mean it is non-payable.

### 4.12 `ScheduledCharging`

Stores a planned charging session.

| Field | Type / rule |
|---|---|
| `activity_id` | Primary key and foreign key to `ScheduledActivity` |
| `charging_location_id` | Foreign key to `Location` |
| `planned_start_soc_pct` | Optional decimal, 0–100 |
| `planned_end_soc_pct` | Optional decimal, 0–100 |
| `expected_energy_kwh` | Optional non-negative decimal |
| `remarks` | Optional text |

The activity's start and end timestamps define the scheduled charging window. The charging location must support charging. Any movement to or from this location must be represented as a separate `NON_REVENUE_MOVEMENT`.

### 4.13 `ScheduledLayover`

Stores planned waiting, recovery, or parking time.

| Field | Type / rule |
|---|---|
| `activity_id` | Primary key and foreign key to `ScheduledActivity` |
| `location_id` | Foreign key to `Location` |
| `layover_purpose` | Terminal recovery, inter-trip layover, overnight parking, other |
| `remarks` | Optional text |

The start and end times are stored in `ScheduledActivity`. The layover must have a location and a positive duration.

## 5. Multi-day schedule handling

The system must use a single operating date as the anchor for the entire schedule.

Example:

- Operating date: `2026-10-21`
- Schedule starts: 21 October at 05:00.
- Overnight layover: 21 October at 22:30 until 22 October at 04:30.
- Schedule finishes: 22 October at 08:00.

Store an overnight layover with `start_day_offset = 0`, `end_day_offset = 1`, start time `22:30`, and end time `04:30`.

For an activity beginning on Day 2 and finishing on Day 3, use offsets `1` and `2`.

Never calculate activity duration by subtracting clock times alone. Calculate it from complete timestamps.

### Recurrence and bus-conflict validation

Daily recurrence means a new operating cycle is planned for each eligible operating date. It does not guarantee that one physical bus can perform every occurrence.

Before publication, calculate the complete time interval of each occurrence and check for conflicts with other schedules assigned to the same bus. If a two-day cycle overlaps the next day's cycle, reject publication unless the system explicitly supports and validates a different operating arrangement.

## 6. Required user interface

### Screen 1 — Vehicle Master

- Create, edit, and deactivate vehicles.
- Capture fleet number, registration number, battery capacity, and home depot.
- Show whether the bus is already assigned to an overlapping published schedule.

### Screen 2 — Location Master

- Create depots, terminals, stops, charging points, and other locations.
- Configure charging capability.
- Search and select locations from all schedule screens.
- Prevent deletion of locations referenced by published schedules.

### Screen 3 — Route and Direction Builder

- Create a route.
- Add one or more directions.
- Configure start and end terminals for each direction.
- Add stops in order.
- Enter distance from previous stop.
- Calculate cumulative distance and total route distance.
- Allow different distances and stop order for each direction.
- Validate that the first and last stops match the direction's terminals.

### Screen 4 — Fixed Schedule Builder

Provide a schedule header containing:

- Schedule code and name.
- Physical bus.
- Recurrence rule.
- Effective dates.
- Timezone.
- Version and publication status.
- Planned operating-cycle start and end.

Provide an ordered activity grid with **Add Passenger Trip**, **Add Movement**, **Add Charging**, and **Add Layover** actions.

Users must be able to:

- Add, edit, remove, and reorder draft activities.
- Select activity origin and destination.
- Enter start and end times with day offsets.
- Select the passenger route and direction.
- Set movement purpose and payability.
- Configure charging and layover details.
- View planned total kilometres and activity durations.
- See gaps, overlaps, and midnight crossings clearly.

### Screen 5 — Passenger Trip and Stop Timetable

When a passenger trip is added:

1. Select a route.
2. Select its direction.
3. Load the direction's ordered stops automatically.
4. Enter scheduled departure time at the origin.
5. Enter arrival and departure times for intermediate stops.
6. Enter arrival time at the destination.
7. Enter planned odometer and expected SOC at each stop.
8. Calculate trip duration and reconcile the planned trip distance against the route distance.

Do not make users manually recreate route stops for every trip. The trip should reference the route master, while the timetable stores trip-specific times and readings.

### Screen 6 — Validation and Publication

Display validation errors and warnings before publication.

Examples:

- Missing trip stop time.
- Invalid route direction.
- Inactive vehicle or location.
- Incorrect stop sequence.
- Odometer decreases unexpectedly.
- SOC outside 0–100%.
- Activity overlap.
- Unexplained time gap.
- Conflicting schedule for the same physical bus.
- Charging activity at a location without charging capability.
- Published version date conflict.

Errors block publication. Warnings may be permitted with an explicit user acknowledgement where appropriate.

Allow the authorized user to publish a valid draft, enter a change reason for revisions, and view previous versions.

### Screen 7 — Schedule Viewer

Provide a read-only view of a published schedule.

Filters:

- Depot.
- Vehicle/fleet number.
- Operating date.
- Schedule code.
- Activity type.
- Publication status.

Show activities in chronological order, including the actual calendar date derived from the operating date and day offset. Include a printable timetable view.

## 7. Validation rules

Implement validation in the backend API as well as the frontend.

| Area | Required validation |
|---|---|
| Schedule | Valid bus, effective dates, recurrence, and at least one activity |
| Sequence | Activity sequence numbers unique within a version |
| Timing | End timestamp later than start timestamp |
| Chronology | No unintended activity overlaps |
| Gaps | Flag unexplained gaps for user review |
| Passenger trip | Route and direction consistent; origin and destination match direction terminals |
| Stops | At least two; ordered correctly; required arrival/departure times present |
| Distance | Trip distance reconciles with route distance within a configurable tolerance |
| Odometer | Non-negative; planned readings should not decrease along a continuous operating cycle |
| SOC | Within 0–100%; allow increases during charging |
| Charging | Valid charging-capable location and positive scheduled duration |
| Movement | Origin, destination, purpose, distance, and payability recorded as applicable |
| Layover | Valid location and positive duration |
| Versioning | Published versions immutable; no overlapping versions for the same schedule |
| Bus allocation | No conflicting published operating cycles for the same physical bus |
| Date handling | Day offsets correctly support midnight and multi-day schedules |

Some values may be optional in the initial version, particularly planned SOC, odometer, and energy. Make their mandatory status configurable rather than inventing readings.

Do not require SOC to decline monotonically during driving: regenerative braking can increase SOC. Use expected readings as planning references, not guaranteed physical outcomes.

## 8. API endpoints

Implement REST APIs with FastAPI. Use consistent JSON schemas, HTTP status codes, and meaningful validation errors.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` / `POST` | `/api/vehicles` | List and create vehicles |
| `GET` / `PUT` | `/api/vehicles/{id}` | Retrieve and update a vehicle |
| `GET` / `POST` | `/api/locations` | List and create locations |
| `GET` / `POST` | `/api/routes` | List and create routes |
| `GET` / `POST` | `/api/routes/{id}/directions` | Manage route directions |
| `GET` / `POST` | `/api/directions/{id}/stops` | Manage ordered direction stops |
| `GET` / `POST` | `/api/schedules` | List and create schedule identities |
| `GET` / `POST` | `/api/schedules/{id}/versions` | List and create schedule versions |
| `GET` / `PUT` | `/api/schedule-versions/{id}` | Retrieve and update a draft version |
| `POST` | `/api/schedule-versions/{id}/activities` | Add an activity |
| `PUT` / `DELETE` | `/api/activities/{id}` | Update or remove an activity in a draft |
| `POST` | `/api/schedule-versions/{id}/validate` | Validate before publication |
| `POST` | `/api/schedule-versions/{id}/publish` | Publish a valid draft |
| `GET` | `/api/schedules/{id}/timeline` | Retrieve a schedule timeline for a date |
| `GET` | `/api/schedule-versions/{id}/print` | Return a printable timetable representation |

All write endpoints must verify that the relevant schedule version is still a draft. Published schedule data must not be changed through ordinary update endpoints.

## 9. Part 2 integration requirements

Part 2 is not the focus of the first build, but design the data model so it can integrate cleanly.

Future actual trip sheets should reference:

- `schedule_id`
- `schedule_version_id`
- `operating_date`
- `activity_id`
- `trip_number` or passenger-trip reference
- `scheduled_stop_time_id` for individual planned stops

Actual data must be stored separately from planned data, including:

- Actual departure and arrival timestamps.
- Actual odometer readings.
- Actual SOC readings.
- Actual charging start/end and energy delivered.
- Actual kilometres and route deviations.
- Cancellation, delay, and operational exception reasons.

A schedule revision must never silently change the planned values attached to an already-created trip sheet. The trip sheet must retain the version that was applicable to it.

## 10. Security and audit requirements

For the initial version:

- Require authenticated access if the application already has a user system.
- Use role-based permissions for viewing, editing drafts, and publishing schedules.
- Record who created, changed, and published each schedule version.
- Keep publication and revision history.
- Use database transactions when publishing.
- Prevent duplicate submissions and invalid foreign-key references.
- Avoid hard deletion of records referenced by published schedules.
- Log important failures without storing sensitive credentials or secrets.

## 11. Acceptance criteria

- [ ] A user can create a vehicle, locations, and a route.
- [ ] A route can have upstream and downstream directions with different distances.
- [ ] Each direction has its own ordered stop list.
- [ ] A recurring schedule can be assigned to one physical bus.
- [ ] A schedule can contain multiple passenger trips.
- [ ] Each passenger trip stores scheduled arrival/departure times at all applicable stops.
- [ ] Each stop can store planned odometer and expected SOC.
- [ ] Depot positioning and return movements can be added separately.
- [ ] Movements can be marked payable, non-payable, or to be confirmed.
- [ ] Charging sessions and layovers can be added as separate activities.
- [ ] The schedule can finish at a designated location other than the depot.
- [ ] Activities can cross midnight and extend into Day 2 or later.
- [ ] Duration calculations remain correct across midnight.
- [ ] The system detects overlapping activities and conflicting bus assignments.
- [ ] A draft can be validated and published.
- [ ] Published schedules are immutable and revisions create new versions.
- [ ] A historical schedule can be viewed using its original version.
- [ ] The schedule viewer displays chronological activities and calendar dates.
- [ ] Backend validation prevents invalid data even when the UI is bypassed.
- [ ] Automated tests cover normal schedules, reverse directions, charging, overnight layovers, multi-day schedules, versioning, and conflicts.

## 12. Recommended implementation sequence

### Phase 1 — Database and masters
Create the database schema, migrations, vehicle master, location master, route master, directions, and stops.

### Phase 2 — Schedule engine
Implement schedule versions, activities, passenger trips, stop times, movements, charging, layovers, and multi-day timestamps.

### Phase 3 — User interface
Build the schedule builder, stop timetable, validation screen, publication workflow, and schedule viewer.

### Phase 4 — Validation and testing
Add backend constraints, conflict checks, audit trails, and automated tests for midnight and multi-day operation.

Build incrementally rather than generating the entire module in one pass.

## 13. Master instruction for the AI coding agent

Build a working web application module for managing fixed, recurring electric-bus schedules.

### Technology
- Frontend: React 18, Vite, Tailwind CSS, React Router, Axios, and Lucide React.
- Backend: Python FastAPI.
- Database: SQLite initially, using SQLAlchemy and Alembic migrations.
- Validation: Pydantic and backend business-rule validation.
- Design the database and service layer so migration to PostgreSQL is practical.

### Functional scope
Implement:
1. Vehicle master.
2. Location master.
3. Route master.
4. Route direction and direction-specific ordered stops.
5. Fixed bus schedule master.
6. Immutable published schedule versions.
7. Ordered scheduled activities.
8. Passenger trips and stop-level timetable.
9. Non-revenue movements with independently configured payability.
10. Charging sessions.
11. Layovers and overnight parking.
12. Planned odometer and SOC references.
13. Multi-day scheduling with day offsets.
14. Schedule validation, publication, revision, and read-only viewing.
15. API and data structures ready for future actual trip sheets.

### Scheduling rules
- Assign each schedule to one physical bus.
- Default recurrence is daily.
- One schedule consists of an ordered sequence of activities.
- A passenger trip references a route and direction.
- Each direction has its own stop sequence and distance values.
- Passenger stops support planned arrival/departure times, planned odometer, and expected SOC.
- Non-passenger movements have a purpose and independent payability status.
- Charging is stationary; movements to/from chargers are separate activities.
- Layovers have a defined location and duration.
- The final schedule destination can be any designated location.
- Schedules may cross midnight and extend into Day 2 or later.
- Use operating date, day offset, local time, and timezone to derive timestamps. Use `Asia/Kolkata` as the default timezone.
- Never calculate durations by subtracting clock times without accounting for date offsets.
- Published schedules are immutable. Changes create new versions.
- Prevent conflicting published operating cycles for the same physical bus.
- Do not overwrite planned values with actual operational data.

### User interface
Build a clear, responsive administrative interface with:
- Master-data screens.
- Route/direction builder.
- Schedule builder with an ordered activity grid.
- Passenger-trip stop timetable.
- Charging and layover editors.
- Movement payability editor.
- Schedule validation and publication workflow.
- Read-only schedule timeline and printable view.

Users must be able to add, edit, reorder, and remove activities while the version is a draft. Automatically load route stops when a route direction is selected.

### Validation
Implement backend and frontend validation for:
- Required fields and foreign keys.
- Valid route/direction relationships.
- Correct stop sequence and terminal matching.
- Required stop times.
- Chronological timestamps and positive activity duration.
- Planned odometer and SOC ranges.
- Charging-capable locations.
- Activity overlaps and unexplained gaps.
- Conflicting bus assignments.
- Published-version immutability.
- Multi-day timestamp correctness.

Treat planned odometer/SOC as reference values. SOC can increase during driving because of regenerative braking. Make the mandatory status of optional planned readings configurable.

### Future integration
Design the schema so Part 2 actual trip sheets can reference the applicable schedule version, operating date, scheduled activity, and scheduled stop. Do not build the complete actual-trip module in this release.

### Engineering requirements
- Implement working frontend and backend code, not just mockups.
- Provide database migrations, environment configuration, sample data, and setup instructions.
- Use reusable components, typed request/response schemas, and a service layer.
- Handle errors visibly and consistently.
- Add automated tests for route directions, stop times, charging, movement payability, midnight crossings, multi-day schedules, versioning, and bus conflicts.
- Do not silently invent operational data.
- Keep the implementation straightforward; avoid microservices or unnecessary abstractions.
- Run the tests and resolve failures before declaring the module complete.

### Definition of done
A user can configure a route, assign it to a physical bus, create a multi-activity recurring schedule, validate and publish it, view the complete chronological timetable across calendar dates, and revise it through a new immutable version. All core functionality must be persisted in the database and enforced by the backend.

## 14. Key architectural recommendation

Build the route/location masters and the schedule engine first. The most important architectural decision is that the schedule is a **versioned, ordered sequence of activities anchored to an operating date**, not a simple list of trips tied to a single calendar day. This keeps the module compatible with Sunlease's actual trip sheets, charging operations, and depot reporting as the system grows.
