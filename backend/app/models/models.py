import datetime as dt

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, Time, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def _now():
    return dt.datetime.utcnow()


class Audited:
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


# --------------------------------------------------------------------------
# Users / audit / settings
# --------------------------------------------------------------------------
class User(Base, Audited):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    full_name = Column(String(150), nullable=False, default="")
    hashed_password = Column(String(255), nullable=False)
    # SUPER_ADMIN or USER; what a USER may do is set per cost center in UserCostCenterRole
    role = Column(String(20), nullable=False, default="USER")
    is_active = Column(Boolean, nullable=False, default=True)
    cost_center_roles = relationship("UserCostCenterRole", back_populates="user", cascade="all, delete-orphan")


# --------------------------------------------------------------------------
# Organisation (multi-tenancy): Company -> Cost Center; roles are held per cost center
# --------------------------------------------------------------------------
class Company(Base, Audited):
    __tablename__ = "companies"
    company_id = Column(Integer, primary_key=True)
    company_code = Column(String(30), unique=True, nullable=False)
    company_name = Column(String(150), unique=True, nullable=False)
    # regional language printed on this company's trip sheets ("" = English only); a cost center may differ
    print_language = Column(String(5), nullable=False, default="te")
    is_active = Column(Boolean, nullable=False, default=True)
    cost_centers = relationship("CostCenter", back_populates="company", order_by="CostCenter.cost_center_code")


class CostCenter(Base, Audited):
    __tablename__ = "cost_centers"
    cost_center_id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=False, index=True)
    cost_center_code = Column(String(30), unique=True, nullable=False)
    cost_center_name = Column(String(150), nullable=False)
    # None = print in the company's language; set it only where this depot differs
    print_language = Column(String(5), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    company = relationship("Company", back_populates="cost_centers")


class UserCostCenterRole(Base):
    __tablename__ = "user_cost_center_roles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    user = relationship("User", back_populates="cost_center_roles")
    cost_center = relationship("CostCenter")
    __table_args__ = (UniqueConstraint("user_id", "cost_center_id", name="uq_user_cost_center"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=_now, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(80), nullable=True)
    action = Column(String(40), nullable=False)
    entity_type = Column(String(60), nullable=False)
    entity_id = Column(String(40), nullable=True)
    detail = Column(Text, nullable=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=True, index=True)


class CostCenterSetting(Base):
    """Validation switches per cost center (see services/settings_service.py)."""
    __tablename__ = "cost_center_settings"
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), primary_key=True)
    key = Column(String(80), primary_key=True)
    value = Column(String(255), nullable=False)


# --------------------------------------------------------------------------
# Masters
# --------------------------------------------------------------------------
class Location(Base, Audited):
    __tablename__ = "locations"
    location_id = Column(Integer, primary_key=True)
    # shared by every cost center of the company (a terminal or charger often serves several)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=True, index=True)
    location_code = Column(String(30), unique=True, nullable=False)
    location_name = Column(String(150), nullable=False)
    # the name in the regional language, printed in brackets on trip sheets (e.g. Telugu)
    location_name_local = Column(String(150), nullable=True)
    location_type = Column(String(20), nullable=False, default="OTHER")
    supports_charging = Column(Boolean, nullable=False, default=False)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class Vehicle(Base, Audited):
    __tablename__ = "vehicles"
    vehicle_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=True, index=True)
    fleet_number = Column(String(30), unique=True, nullable=False)
    registration_number = Column(String(30), unique=True, nullable=False)
    battery_capacity_kwh = Column(Numeric(8, 2), nullable=True)
    home_depot_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    status = Column(String(12), nullable=False, default="ACTIVE")
    home_depot = relationship("Location")
    cost_center = relationship("CostCenter")
    __table_args__ = (CheckConstraint("battery_capacity_kwh IS NULL OR battery_capacity_kwh > 0", name="ck_vehicle_battery"),)


class Route(Base, Audited):
    __tablename__ = "routes"
    route_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=True, index=True)
    route_code = Column(String(30), unique=True, nullable=False)
    route_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="ACTIVE")
    directions = relationship("RouteDirection", back_populates="route", order_by="RouteDirection.direction_id")
    cost_center = relationship("CostCenter")


class RouteDirection(Base, Audited):
    __tablename__ = "route_directions"
    direction_id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.route_id"), nullable=False, index=True)
    direction_code = Column(String(30), nullable=False)
    direction_name = Column(String(150), nullable=False)
    start_terminal_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    end_terminal_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    total_distance_km = Column(Numeric(9, 3), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    route = relationship("Route", back_populates="directions")
    start_terminal = relationship("Location", foreign_keys=[start_terminal_id])
    end_terminal = relationship("Location", foreign_keys=[end_terminal_id])
    stops = relationship("RouteStop", back_populates="direction", order_by="RouteStop.stop_sequence",
                         cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("route_id", "direction_code", name="uq_direction_code"),)


class RouteStop(Base):
    __tablename__ = "route_stops"
    route_stop_id = Column(Integer, primary_key=True)
    direction_id = Column(Integer, ForeignKey("route_directions.direction_id"), nullable=False, index=True)
    stop_sequence = Column(Integer, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    distance_from_previous_km = Column(Numeric(9, 3), nullable=False, default=0)
    cumulative_distance_km = Column(Numeric(9, 3), nullable=False, default=0)
    is_pickup_dropoff_stop = Column(Boolean, nullable=False, default=True)
    direction = relationship("RouteDirection", back_populates="stops")
    location = relationship("Location")
    __table_args__ = (
        UniqueConstraint("direction_id", "stop_sequence", name="uq_stop_sequence"),
        CheckConstraint("stop_sequence > 0", name="ck_stop_seq_pos"),
        CheckConstraint("distance_from_previous_km >= 0", name="ck_stop_dist"),
    )


class Employee(Base, Audited):
    """One row per employment stint. A rejoiner gets a NEW row (same
    employee_number, new start_date). end_date is the inclusive last day."""
    __tablename__ = "employees"
    employee_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=True, index=True)
    employee_number = Column(String(30), nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    designation = Column(String(100), nullable=True)
    staff_type = Column(String(20), nullable=False, default="DRIVER")
    home_depot_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    status = Column(String(12), nullable=False, default="ACTIVE")
    source = Column(String(10), nullable=False, default="MANUAL")
    last_synced_at = Column(DateTime, nullable=True)
    home_depot = relationship("Location")
    __table_args__ = (
        UniqueConstraint("employee_number", "start_date", name="uq_employee_stint"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_employee_dates"),
    )


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------
class BusSchedule(Base):
    __tablename__ = "bus_schedules"
    schedule_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=True, index=True)
    schedule_code = Column(String(30), unique=True, nullable=False)
    schedule_name = Column(String(150), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.vehicle_id"), nullable=False, index=True)
    recurrence_type = Column(String(12), nullable=False, default="DAILY")
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    timezone = Column(String(40), nullable=False, default="Asia/Kolkata")
    status = Column(String(12), nullable=False, default="DRAFT")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    vehicle = relationship("Vehicle")
    cost_center = relationship("CostCenter")
    versions = relationship("ScheduleVersion", back_populates="schedule", order_by="ScheduleVersion.version_number")


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"
    schedule_version_id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=True)
    status = Column(String(12), nullable=False, default="DRAFT")
    published_at = Column(DateTime, nullable=True)
    published_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    change_reason = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    # what publishing a later version changed here, so unpublishing that version can undo it
    superseded_by_version_id = Column(Integer, nullable=True)
    prior_status = Column(String(12), nullable=True)
    prior_valid_to = Column(Date, nullable=True)
    # crew pattern for trip sheets: one driver for the day, or the shifts below
    crew_mode = Column(String(10), nullable=False, default="SINGLE")
    conductor_required = Column(Boolean, nullable=False, default=False)
    schedule = relationship("BusSchedule", back_populates="versions")
    shifts = relationship("ScheduleShift", back_populates="version", order_by="ScheduleShift.shift_number",
                          cascade="all, delete-orphan")
    activities = relationship("ScheduledActivity", back_populates="version",
                              order_by="ScheduledActivity.sequence_number", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("schedule_id", "version_number", name="uq_schedule_version"),)


class ScheduledActivity(Base):
    __tablename__ = "scheduled_activities"
    activity_id = Column(Integer, primary_key=True)
    schedule_version_id = Column(Integer, ForeignKey("schedule_versions.schedule_version_id"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    activity_type = Column(String(24), nullable=False)
    origin_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    destination_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    start_day_offset = Column(Integer, nullable=False, default=0)
    scheduled_start_time = Column(Time, nullable=False)
    end_day_offset = Column(Integer, nullable=False, default=0)
    scheduled_end_time = Column(Time, nullable=False)
    remarks = Column(Text, nullable=True)
    version = relationship("ScheduleVersion", back_populates="activities")
    origin = relationship("Location", foreign_keys=[origin_location_id])
    destination = relationship("Location", foreign_keys=[destination_location_id])
    trip = relationship("ScheduledTrip", uselist=False, back_populates="activity", cascade="all, delete-orphan")
    movement = relationship("ScheduledMovement", uselist=False, back_populates="activity", cascade="all, delete-orphan")
    charging = relationship("ScheduledCharging", uselist=False, back_populates="activity", cascade="all, delete-orphan")
    layover = relationship("ScheduledLayover", uselist=False, back_populates="activity", cascade="all, delete-orphan")
    halt = relationship("ScheduledHalt", uselist=False, back_populates="activity", cascade="all, delete-orphan")
    stop_times = relationship("ScheduledStopTime", back_populates="activity", order_by="ScheduledStopTime.stop_sequence",
                              cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("schedule_version_id", "sequence_number", name="uq_activity_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_activity_seq"),
        CheckConstraint("start_day_offset >= 0 AND end_day_offset >= 0", name="ck_activity_offsets"),
    )


class ScheduledTrip(Base):
    __tablename__ = "scheduled_trips"
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), primary_key=True)
    schedule_version_id = Column(Integer, ForeignKey("schedule_versions.schedule_version_id"), nullable=False)
    trip_number = Column(String(30), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.route_id"), nullable=False)
    direction_id = Column(Integer, ForeignKey("route_directions.direction_id"), nullable=False)
    planned_distance_km = Column(Numeric(9, 3), nullable=False)
    planned_start_soc_pct = Column(Numeric(5, 2), nullable=True)
    planned_end_soc_pct = Column(Numeric(5, 2), nullable=True)
    activity = relationship("ScheduledActivity", back_populates="trip")
    route = relationship("Route")
    direction = relationship("RouteDirection")
    __table_args__ = (
        UniqueConstraint("schedule_version_id", "trip_number", name="uq_trip_number"),
        CheckConstraint("planned_distance_km > 0", name="ck_trip_dist"),
    )


class ScheduledStopTime(Base):
    __tablename__ = "scheduled_stop_times"
    scheduled_stop_time_id = Column(Integer, primary_key=True)
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), nullable=False, index=True)
    route_stop_id = Column(Integer, ForeignKey("route_stops.route_stop_id"), nullable=False)
    stop_sequence = Column(Integer, nullable=False)
    arrival_day_offset = Column(Integer, nullable=True)
    scheduled_arrival_time = Column(Time, nullable=True)
    departure_day_offset = Column(Integer, nullable=True)
    scheduled_departure_time = Column(Time, nullable=True)
    planned_soc_pct = Column(Numeric(5, 2), nullable=True)
    activity = relationship("ScheduledActivity", back_populates="stop_times")
    route_stop = relationship("RouteStop")
    __table_args__ = (UniqueConstraint("activity_id", "stop_sequence", name="uq_stoptime_seq"),)


class ScheduledMovement(Base):
    __tablename__ = "scheduled_movements"
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), primary_key=True)
    movement_purpose = Column(String(24), nullable=False)
    planned_distance_km = Column(Numeric(9, 3), nullable=False, default=0)
    planned_start_soc_pct = Column(Numeric(5, 2), nullable=True)
    planned_end_soc_pct = Column(Numeric(5, 2), nullable=True)
    payability_status = Column(String(16), nullable=False, default="TO_BE_CONFIRMED")
    payment_basis = Column(String(24), nullable=False, default="UNSPECIFIED")
    activity = relationship("ScheduledActivity", back_populates="movement")


class ScheduledCharging(Base):
    __tablename__ = "scheduled_charging"
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), primary_key=True)
    charging_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    planned_start_soc_pct = Column(Numeric(5, 2), nullable=True)
    planned_end_soc_pct = Column(Numeric(5, 2), nullable=True)
    expected_energy_kwh = Column(Numeric(9, 2), nullable=True)
    activity = relationship("ScheduledActivity", back_populates="charging")
    charging_location = relationship("Location")


class ScheduledLayover(Base):
    __tablename__ = "scheduled_layovers"
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    layover_purpose = Column(String(24), nullable=False, default="OTHER")
    # the bus stays powered (A/C on), so SOC can fall during a layover
    planned_start_soc_pct = Column(Numeric(5, 2), nullable=True)
    planned_end_soc_pct = Column(Numeric(5, 2), nullable=True)
    activity = relationship("ScheduledActivity", back_populates="layover")
    location = relationship("Location")


class ScheduledHalt(Base):
    """One undivided off-service block (depot or night-halt terminal). Washing, charging and
    maintenance may happen inside it but are not scheduled separately, so SOC may rise or fall."""
    __tablename__ = "scheduled_halts"
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    planned_start_soc_pct = Column(Numeric(5, 2), nullable=True)
    planned_end_soc_pct = Column(Numeric(5, 2), nullable=True)
    activity = relationship("ScheduledActivity", back_populates="halt")
    location = relationship("Location")


class ScheduleShift(Base):
    """A crew shift on a schedule version (crew_mode SHIFTS). Locked with the version once published."""
    __tablename__ = "schedule_shifts"
    shift_id = Column(Integer, primary_key=True)
    schedule_version_id = Column(Integer, ForeignKey("schedule_versions.schedule_version_id"), nullable=False, index=True)
    shift_number = Column(Integer, nullable=False)
    shift_name = Column(String(40), nullable=False)
    start_day_offset = Column(Integer, nullable=False, default=0)
    start_time = Column(Time, nullable=False)
    end_day_offset = Column(Integer, nullable=False, default=0)
    end_time = Column(Time, nullable=False)
    change_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    version = relationship("ScheduleVersion", back_populates="shifts")
    change_location = relationship("Location")
    __table_args__ = (UniqueConstraint("schedule_version_id", "shift_number", name="uq_shift_number"),)


# --------------------------------------------------------------------------
# Trip sheets (Part 2): actuals entered from the paper sheet, against the exact published version
# --------------------------------------------------------------------------
class TripReason(Base, Audited):
    """Cancellation / curtailment / delay reasons, per company, with a default attribution."""
    __tablename__ = "trip_reasons"
    reason_id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=False, index=True)
    reason_code = Column(String(30), nullable=False)
    reason_name = Column(String(150), nullable=False)
    reason_name_local = Column(String(150))      # printed in brackets on the paper sheet
    default_attributable_to = Column(String(12), nullable=False, default="OPERATOR")
    is_active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("company_id", "reason_code", name="uq_reason_code"),)


class SheetScan(Base, Audited):
    """One uploaded scan: a multi-page PDF of paper sheets for a cost center (a whole day, or one bus).

    A new upload for the same cost center and date supersedes the earlier one and rewrites the draft
    sheets it covers, so re-scanning a corrected batch is the normal way to fix a bad scan.
    """
    __tablename__ = "sheet_scans"
    scan_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=False, index=True)
    operating_date = Column(Date, nullable=True, index=True)   # None until a page says which date it is
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=True)   # single-bus upload
    file_name = Column(String(255), nullable=False)
    page_count = Column(Integer, nullable=False, default=0)
    status = Column(String(12), nullable=False, default="PROCESSING")   # PROCESSING / DONE / FAILED / SUPERSEDED
    message = Column(Text, nullable=True)                              # why it failed, for the clerk
    superseded_by = Column(Integer, ForeignKey("sheet_scans.scan_id"), nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    pages = relationship("SheetScanPage", back_populates="scan", order_by="SheetScanPage.page_no",
                         cascade="all, delete-orphan")


class SheetScanPage(Base, Audited):
    """One page of a scan: which sheet it turned out to be, and what could not be read."""
    __tablename__ = "sheet_scan_pages"
    page_id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey("sheet_scans.scan_id"), nullable=False, index=True)
    page_no = Column(Integer, nullable=False)
    sheet_id = Column(Integer, ForeignKey("trip_sheets.sheet_id"), nullable=True)
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=True)
    version_number = Column(Integer, nullable=True)
    read_date = Column(Date, nullable=True)                 # the date read off the page
    # OK / WARNED / UNREADABLE / SKIPPED / REJECTED (another bus or day than it was uploaded against)
    status = Column(String(12), nullable=False, default="OK")
    # [{field, run, severity, code, message}] - each one points at a single box group on the entry screen
    issues = Column(Text, nullable=True)
    fields_read = Column(Integer, nullable=False, default=0)
    fields_unsure = Column(Integer, nullable=False, default=0)
    image_path = Column(String(255), nullable=True)         # registered page, kept so a clerk can compare
    scan = relationship("SheetScan", back_populates="pages")


class TripSheet(Base, Audited):
    __tablename__ = "trip_sheets"
    sheet_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=False, index=True)
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=False, index=True)
    schedule_version_id = Column(Integer, ForeignKey("schedule_versions.schedule_version_id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.vehicle_id"), nullable=False, index=True)
    operating_date = Column(Date, nullable=False, index=True)
    paper_sheet_no = Column(String(40), nullable=True)
    # version printed on an undated (reusable) paper sheet; warns when another version applies on the date
    paper_version_number = Column(Integer, nullable=True)
    # bus change: another bus ran the schedule from a given run (registration as written on the paper)
    bus_change_registration = Column(String(20), nullable=True)
    bus_change_vehicle_id = Column(Integer, ForeignKey("vehicles.vehicle_id"), nullable=True)
    bus_change_from_row_id = Column(Integer, nullable=True)   # a row of this sheet (no FK: avoids a sheet<->row cycle)
    bus_change_reason_id = Column(Integer, ForeignKey("trip_reasons.reason_id"), nullable=True)
    status = Column(String(12), nullable=False, default="DRAFT")
    remarks = Column(Text, nullable=True)
    # set when the sheet was filled from a scan, so the board can show it was not keyed by hand
    scanned_page_id = Column(Integer, nullable=True)        # a sheet_scan_pages row (no FK: pages are replaceable)
    # last validation result, kept so the board can show a warning or error symbol without revalidating
    validation_errors = Column(Integer, nullable=False, default=0)
    validation_warnings = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    schedule = relationship("BusSchedule")
    version = relationship("ScheduleVersion")
    vehicle = relationship("Vehicle", foreign_keys=[vehicle_id])
    bus_change_vehicle = relationship("Vehicle", foreign_keys=[bus_change_vehicle_id])
    bus_change_reason = relationship("TripReason")
    rows = relationship("TripSheetRow", back_populates="sheet", order_by="TripSheetRow.row_sequence",
                        cascade="all, delete-orphan")
    crew = relationship("TripSheetCrew", back_populates="sheet", order_by="TripSheetCrew.crew_id",
                        cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("schedule_id", "operating_date", name="uq_sheet_schedule_date"),)


class TripSheetRow(Base):
    """Actuals for one planned activity (activity_id set) or an unplanned extra run (activity_id null)."""
    __tablename__ = "trip_sheet_rows"
    row_id = Column(Integer, primary_key=True)
    sheet_id = Column(Integer, ForeignKey("trip_sheets.sheet_id"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("scheduled_activities.activity_id"), nullable=True)
    row_sequence = Column(Integer, nullable=False)
    status = Column(String(12), nullable=False, default="PENDING")
    actual_start_day_offset = Column(Integer, nullable=True)
    actual_start_time = Column(Time, nullable=True)
    actual_end_day_offset = Column(Integer, nullable=True)
    actual_end_time = Column(Time, nullable=True)
    start_odometer_km = Column(Numeric(10, 1), nullable=True)
    end_odometer_km = Column(Numeric(10, 1), nullable=True)
    start_soc_pct = Column(Numeric(5, 2), nullable=True)
    end_soc_pct = Column(Numeric(5, 2), nullable=True)
    energy_kwh = Column(Numeric(9, 2), nullable=True)
    # partial trip: the last stop reached; billed km run up to it
    stopped_at_route_stop_id = Column(Integer, ForeignKey("route_stops.route_stop_id"), nullable=True)
    reason_id = Column(Integer, ForeignKey("trip_reasons.reason_id"), nullable=True)
    attributable_to = Column(String(12), nullable=True)
    remarks = Column(Text, nullable=True)
    # extra (unplanned) runs only
    extra_from_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    extra_to_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    extra_payable = Column(Boolean, nullable=False, default=False)
    sheet = relationship("TripSheet", back_populates="rows")
    activity = relationship("ScheduledActivity")
    stopped_at = relationship("RouteStop")
    reason = relationship("TripReason")
    extra_from = relationship("Location", foreign_keys=[extra_from_location_id])
    extra_to = relationship("Location", foreign_keys=[extra_to_location_id])
    stops = relationship("TripSheetStop", back_populates="row", order_by="TripSheetStop.stop_sequence",
                         cascade="all, delete-orphan")


class TripSheetStop(Base):
    """Optional stop-level actuals for a passenger trip row."""
    __tablename__ = "trip_sheet_stops"
    trip_stop_id = Column(Integer, primary_key=True)
    row_id = Column(Integer, ForeignKey("trip_sheet_rows.row_id"), nullable=False, index=True)
    scheduled_stop_time_id = Column(Integer, ForeignKey("scheduled_stop_times.scheduled_stop_time_id"), nullable=False)
    stop_sequence = Column(Integer, nullable=False)
    arrival_day_offset = Column(Integer, nullable=True)
    arrival_time = Column(Time, nullable=True)
    departure_day_offset = Column(Integer, nullable=True)
    departure_time = Column(Time, nullable=True)
    odometer_km = Column(Numeric(10, 1), nullable=True)
    soc_pct = Column(Numeric(5, 2), nullable=True)
    row = relationship("TripSheetRow", back_populates="stops")
    scheduled_stop = relationship("ScheduledStopTime")


class TripSheetCrew(Base):
    """A crew member's duty on the sheet. A driver change ends one duty and starts the next at the same time."""
    __tablename__ = "trip_sheet_crew"
    crew_id = Column(Integer, primary_key=True)
    sheet_id = Column(Integer, ForeignKey("trip_sheets.sheet_id"), nullable=False, index=True)
    crew_role = Column(String(12), nullable=False)
    shift_id = Column(Integer, ForeignKey("schedule_shifts.shift_id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=True)
    duty_start_day_offset = Column(Integer, nullable=True)
    duty_start_time = Column(Time, nullable=True)
    duty_end_day_offset = Column(Integer, nullable=True)
    duty_end_time = Column(Time, nullable=True)
    replaces_crew_id = Column(Integer, ForeignKey("trip_sheet_crew.crew_id"), nullable=True)
    handover_reason = Column(Text, nullable=True)
    sheet = relationship("TripSheet", back_populates="crew")
    shift = relationship("ScheduleShift")
    employee = relationship("Employee")


# --------------------------------------------------------------------------
# Duty roster: who is planned to work which bus on which date, and who actually did
# --------------------------------------------------------------------------
class EmployeeAvailability(Base, Audited):
    """A date range in which an employee is not available for duty. A depot-level
    marker (the clerk's own note), not HRMS leave approval."""
    __tablename__ = "employee_availability"
    availability_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=False, index=True)
    status = Column(String(12), nullable=False)
    from_date = Column(Date, nullable=False, index=True)
    to_date = Column(Date, nullable=False)          # inclusive last day
    remarks = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    employee = relationship("Employee")
    __table_args__ = (
        CheckConstraint("to_date >= from_date", name="ck_availability_dates"),
        Index("ix_availability_employee_dates", "employee_id", "from_date", "to_date"),
    )


class DutyRoster(Base, Audited):
    """A roster period for one cost center. Holds the versions; `locked_through` is the
    last closed day, which no version may change."""
    __tablename__ = "duty_rosters"
    roster_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=False, index=True)
    roster_code = Column(String(30), nullable=False)
    roster_name = Column(String(120), nullable=True)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)        # inclusive last day
    locked_through = Column(Date, nullable=True)    # last closed day; null = nothing closed yet
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    versions = relationship("DutyRosterVersion", back_populates="roster",
                            order_by="DutyRosterVersion.version_number", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("cost_center_id", "roster_code", name="uq_roster_code"),
        CheckConstraint("period_to >= period_from", name="ck_roster_period"),
    )


class DutyRosterVersion(Base):
    """An immutable published copy of the WHOLE period. A revision copies every
    assignment forward, completed days included, so exactly one version is ever live."""
    __tablename__ = "duty_roster_versions"
    roster_version_id = Column(Integer, primary_key=True)
    roster_id = Column(Integer, ForeignKey("duty_rosters.roster_id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    status = Column(String(12), nullable=False, default="DRAFT")
    published_at = Column(DateTime, nullable=True)
    published_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    change_reason = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    # what publishing a later version changed here, so unpublishing that version can undo it
    superseded_by_version_id = Column(Integer, nullable=True)
    prior_status = Column(String(12), nullable=True)
    roster = relationship("DutyRoster", back_populates="versions")
    assignments = relationship("DutyAssignment", back_populates="version",
                               order_by="DutyAssignment.duty_date", cascade="all, delete-orphan")
    extras = relationship("DutyExtra", back_populates="version",
                          order_by="DutyExtra.duty_date", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("roster_id", "version_number", name="uq_roster_version"),)


class DutyPattern(Base, Audited):
    """A repeating crew cycle used to generate a draft roster: `cycle_days` days of slots,
    with ordered members rotating through them."""
    __tablename__ = "duty_patterns"
    pattern_id = Column(Integer, primary_key=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.cost_center_id"), nullable=False, index=True)
    pattern_code = Column(String(30), nullable=False)
    pattern_name = Column(String(120), nullable=True)
    cycle_days = Column(Integer, nullable=False, default=7)
    is_active = Column(Boolean, nullable=False, default=True)
    slots = relationship("DutyPatternSlot", back_populates="pattern", order_by="DutyPatternSlot.cycle_day",
                         cascade="all, delete-orphan")
    members = relationship("DutyPatternMember", back_populates="pattern",
                           order_by="DutyPatternMember.member_order", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("cost_center_id", "pattern_code", name="uq_pattern_code"),
        CheckConstraint("cycle_days BETWEEN 1 AND 90", name="ck_pattern_cycle"),
    )


class DutyPatternSlot(Base):
    """One duty (or a rest day) on one day of the cycle. `schedule_id` null = off day."""
    __tablename__ = "duty_pattern_slots"
    slot_id = Column(Integer, primary_key=True)
    pattern_id = Column(Integer, ForeignKey("duty_patterns.pattern_id"), nullable=False, index=True)
    cycle_day = Column(Integer, nullable=False)     # 0 .. cycle_days - 1
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=True)
    shift_number = Column(Integer, nullable=True)   # matches ScheduleShift.shift_number of the live version
    crew_role = Column(String(12), nullable=False, default="DRIVER")
    pattern = relationship("DutyPattern", back_populates="slots")
    schedule = relationship("BusSchedule")
    __table_args__ = (
        UniqueConstraint("pattern_id", "cycle_day", "schedule_id", "shift_number", "crew_role",
                         name="uq_pattern_slot"),
    )


class DutyPatternMember(Base):
    """An employee's place in the rotation: member N starts the cycle N days in."""
    __tablename__ = "duty_pattern_members"
    member_id = Column(Integer, primary_key=True)
    pattern_id = Column(Integer, ForeignKey("duty_patterns.pattern_id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=False)
    member_order = Column(Integer, nullable=False)
    pattern = relationship("DutyPattern", back_populates="members")
    employee = relationship("Employee")
    __table_args__ = (
        UniqueConstraint("pattern_id", "employee_id", name="uq_pattern_member"),
        UniqueConstraint("pattern_id", "member_order", name="uq_pattern_member_order"),
    )


class DutyAssignment(Base):
    """The planned duty: one employee in one crew slot of one schedule on one date.
    Frozen with its version once published."""
    __tablename__ = "duty_assignments"
    assignment_id = Column(Integer, primary_key=True)
    roster_version_id = Column(Integer, ForeignKey("duty_roster_versions.roster_version_id"),
                               nullable=False, index=True)
    duty_date = Column(Date, nullable=False, index=True)
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=False)
    shift_id = Column(Integer, ForeignKey("schedule_shifts.shift_id"), nullable=True)   # null: SINGLE crew mode
    crew_role = Column(String(12), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=True)   # null: slot left open
    source = Column(String(10), nullable=False, default="MANUAL")
    remarks = Column(Text, nullable=True)
    version = relationship("DutyRosterVersion", back_populates="assignments")
    schedule = relationship("BusSchedule")
    shift = relationship("ScheduleShift")
    employee = relationship("Employee")
    __table_args__ = (
        UniqueConstraint("roster_version_id", "duty_date", "schedule_id", "shift_id", "crew_role",
                         name="uq_duty_assignment"),
        Index("ix_duty_assignment_date", "roster_version_id", "duty_date"),
    )


class DutyActual(Base):
    """What really happened in a duty slot, entered by hand day by day. Keyed on the
    ROSTER, not a version, so a new version never orphans or duplicates a recorded day.

    One planned slot can hold several rows, one per SEGMENT: a duty handed over part-way
    through ends one segment and starts the next at the same moment, the way a trip sheet's
    crew change does.
    """
    __tablename__ = "duty_actuals"
    actual_id = Column(Integer, primary_key=True)
    roster_id = Column(Integer, ForeignKey("duty_rosters.roster_id"), nullable=False, index=True)
    duty_date = Column(Date, nullable=False, index=True)
    # a spare or shunting duty has no bus, so schedule_id is empty and duty_type says which it is
    duty_type = Column(String(10), nullable=False, default="SCHEDULE")
    schedule_id = Column(Integer, ForeignKey("bus_schedules.schedule_id"), nullable=True)
    shift_id = Column(Integer, ForeignKey("schedule_shifts.shift_id"), nullable=True)
    slot_index = Column(Integer, nullable=False, default=0)      # 0 for a bus duty, 1.. for spares
    crew_role = Column(String(12), nullable=False)
    planned_employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=True)
    actual_employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=True)
    # which stretch of the duty this row covers: 0 unless the duty was handed over
    segment = Column(Integer, nullable=False, default=0)
    # the hours this person actually held, snapshotted from the plan when the day is opened.
    # Day offsets matter: a duty can run past midnight.
    duty_start_day_offset = Column(Integer, nullable=True)
    duty_start_time = Column(Time, nullable=True)
    duty_end_day_offset = Column(Integer, nullable=True)
    duty_end_time = Column(Time, nullable=True)
    # the segment this one took over from, and why that person stopped
    replaces_actual_id = Column(Integer, ForeignKey("duty_actuals.actual_id"), nullable=True)
    handover_reason = Column(Text, nullable=True)
    status = Column(String(14), nullable=False, default="AS_PLANNED")
    reason_id = Column(Integer, ForeignKey("trip_reasons.reason_id"), nullable=True)
    remarks = Column(Text, nullable=True)
    # the version that was live when the day was opened, kept so the comparison can say
    # which plan the actual was recorded against
    roster_version_id = Column(Integer, ForeignKey("duty_roster_versions.roster_version_id"), nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    recorded_at = Column(DateTime, nullable=True)
    roster = relationship("DutyRoster")
    schedule = relationship("BusSchedule")
    shift = relationship("ScheduleShift")
    planned_employee = relationship("Employee", foreign_keys=[planned_employee_id])
    actual_employee = relationship("Employee", foreign_keys=[actual_employee_id])
    reason = relationship("TripReason")
    __table_args__ = (
        UniqueConstraint("roster_id", "duty_date", "duty_type", "schedule_id", "shift_id",
                         "crew_role", "slot_index", "segment", name="uq_duty_actual"),
        Index("ix_duty_actual_date", "roster_id", "duty_date"),
    )


class DutyExtra(Base):
    """A duty with no bus: a spare on standby, or a shunting driver. Added per day, as many as
    the depot needs, so it is a row of its own rather than a slot on a schedule."""
    __tablename__ = "duty_extras"
    extra_id = Column(Integer, primary_key=True)
    roster_version_id = Column(Integer, ForeignKey("duty_roster_versions.roster_version_id"),
                               nullable=False, index=True)
    duty_date = Column(Date, nullable=False, index=True)
    duty_type = Column(String(10), nullable=False)
    crew_role = Column(String(12), nullable=False, default="DRIVER")
    slot_index = Column(Integer, nullable=False, default=1)     # 1st spare, 2nd spare, ...
    employee_id = Column(Integer, ForeignKey("employees.employee_id"), nullable=True)
    # a shunting duty may be timed; a spare is usually just "on call that day"
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    remarks = Column(Text, nullable=True)
    version = relationship("DutyRosterVersion", back_populates="extras")
    employee = relationship("Employee")
    __table_args__ = (
        UniqueConstraint("roster_version_id", "duty_date", "duty_type", "crew_role", "slot_index",
                         name="uq_duty_extra"),
        Index("ix_duty_extra_date", "roster_version_id", "duty_date"),
    )
