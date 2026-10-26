import datetime as dt
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    Attribution, AvailabilityStatus, CrewMode, CrewRole, DutyActualStatus, DutyType, RowStatus,
    ActivityType, LayoverPurpose, LocationType, MovementPurpose, Payability, PaymentBasis,
    Role, StaffType, VehicleStatus,
)

Pct = Optional[Decimal]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _pct(v):
    if v is not None and not (0 <= v <= 100):
        raise ValueError("must be between 0 and 100")
    return v


def _in(options):
    def check(v):
        if v not in options:
            raise ValueError(f"must be one of {', '.join(options)}")
        return v
    return check


# ---- auth / users -------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


class CostCenterRoleIn(BaseModel):
    cost_center_id: int
    role: str
    chk_r = field_validator("role")(_in(Role.ALL))


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    role: str                      # SUPER_ADMIN or USER
    is_active: bool


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    full_name: str = ""
    password: str = Field(min_length=6)
    is_super_admin: bool = False
    cost_center_roles: list[CostCenterRoleIn] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6)
    is_super_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    cost_center_roles: Optional[list[CostCenterRoleIn]] = None


# ---- organisation -------------------------------------------------------
PRINT_LANGUAGES = ("", "te", "kn", "ta", "hi")   # "" = English only


class CompanyIn(BaseModel):
    company_code: str = Field(min_length=1, max_length=30)
    company_name: str = Field(min_length=1, max_length=150)
    print_language: str = "te"
    is_active: bool = True
    chk_lang = field_validator("print_language")(_in(PRINT_LANGUAGES))


class CostCenterIn(BaseModel):
    company_id: int
    cost_center_code: str = Field(min_length=1, max_length=30)
    cost_center_name: str = Field(min_length=1, max_length=150)
    print_language: Optional[str] = None          # None = use the company's
    is_active: bool = True

    @field_validator("print_language")
    @classmethod
    def _lang(cls, v):
        if v is not None and v not in PRINT_LANGUAGES:
            raise ValueError(f"must be one of {PRINT_LANGUAGES}")
        return v


# ---- masters ------------------------------------------------------------
class LocationIn(BaseModel):
    location_code: str = Field(min_length=1, max_length=30)
    location_name: str = Field(min_length=1)
    location_name_local: Optional[str] = Field(default=None, max_length=150)
    location_type: str = LocationType.OTHER
    supports_charging: bool = False
    latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    is_active: bool = True
    chk_t = field_validator("location_type")(_in(LocationType.ALL))


class LocationOut(LocationIn, ORM):
    location_id: int
    company_id: Optional[int] = None


class VehicleIn(BaseModel):
    fleet_number: str = Field(min_length=1, max_length=30)
    registration_number: str = Field(min_length=1, max_length=30)
    battery_capacity_kwh: Optional[Decimal] = Field(default=None, gt=0)
    home_depot_id: Optional[int] = None
    status: str = VehicleStatus.ACTIVE
    chk_s = field_validator("status")(_in(VehicleStatus.ALL))


class VehicleOut(VehicleIn, ORM):
    vehicle_id: int
    cost_center_id: Optional[int] = None
    home_depot_code: Optional[str] = None
    home_depot_name: Optional[str] = None
    assigned_schedules: list[str] = []
    in_use: bool = False


class RouteIn(BaseModel):
    route_code: str = Field(min_length=1, max_length=30)
    route_name: str = Field(min_length=1)
    description: Optional[str] = None
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class DirectionIn(BaseModel):
    direction_code: str = Field(min_length=1, max_length=30)
    direction_name: str = Field(min_length=1)
    start_terminal_id: int
    end_terminal_id: int
    is_active: bool = True


class StopIn(BaseModel):
    location_id: int
    distance_from_previous_km: Decimal = Field(default=Decimal(0), ge=0)
    is_pickup_dropoff_stop: bool = True


class StopsReplaceIn(BaseModel):
    """Whole ordered stop list for a direction; sequence = list order."""
    stops: list[StopIn]


class StopOut(ORM):
    route_stop_id: int
    stop_sequence: int
    location_id: int
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    distance_from_previous_km: Decimal
    cumulative_distance_km: Decimal
    is_pickup_dropoff_stop: bool


class DirectionOut(ORM):
    direction_id: int
    route_id: int
    direction_code: str
    direction_name: str
    start_terminal_id: int
    end_terminal_id: int
    start_terminal_name: Optional[str] = None
    end_terminal_name: Optional[str] = None
    total_distance_km: Decimal
    is_active: bool
    stops: list[StopOut] = []


class RouteOut(ORM):
    route_id: int
    cost_center_id: Optional[int] = None
    route_code: str
    route_name: str
    description: Optional[str]
    status: str
    in_use: bool = False
    directions: list[DirectionOut] = []


class EmployeeIn(BaseModel):
    employee_number: str = Field(min_length=1, max_length=30)
    full_name: str = Field(min_length=1)
    designation: Optional[str] = None
    staff_type: str = StaffType.DRIVER
    home_depot_id: Optional[int] = None
    start_date: dt.date
    end_date: Optional[dt.date] = None
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    chk_t = field_validator("staff_type")(_in(StaffType.ALL))

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class EmployeeOut(EmployeeIn, ORM):
    employee_id: int
    cost_center_id: Optional[int] = None
    source: str
    last_synced_at: Optional[dt.datetime] = None
    home_depot_code: Optional[str] = None
    home_depot_name: Optional[str] = None


class AvailabilityIn(BaseModel):
    employee_id: int
    status: str
    from_date: dt.date
    to_date: dt.date
    remarks: Optional[str] = None
    chk_s = field_validator("status")(_in(AvailabilityStatus.ALL))

    @model_validator(mode="after")
    def _dates(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date cannot be before from_date")
        return self


class AvailabilityOut(AvailabilityIn, ORM):
    availability_id: int
    cost_center_id: int
    employee_number: Optional[str] = None
    employee_name: Optional[str] = None
    staff_type: Optional[str] = None


class EmployeeTransferIn(BaseModel):
    cost_center_id: int
    # required only when the employee has already been used here; their stint ends the day before
    effective_from: Optional[dt.date] = None


class RosterIn(BaseModel):
    roster_code: str = Field(min_length=1, max_length=30)
    roster_name: Optional[str] = None
    period_from: dt.date
    period_to: dt.date

    @model_validator(mode="after")
    def _dates(self):
        if self.period_to < self.period_from:
            raise ValueError("period_to cannot be before period_from")
        return self


class RosterOut(ORM):
    roster_id: int
    cost_center_id: int
    roster_code: str
    roster_name: Optional[str] = None
    period_from: dt.date
    period_to: dt.date
    locked_through: Optional[dt.date] = None
    versions: list[dict] = []


class AssignmentIn(BaseModel):
    """One cell of the grid. `shift_number` is null when the schedule runs on one crew."""
    duty_date: dt.date
    schedule_id: int
    shift_number: Optional[int] = None
    crew_role: str = CrewRole.DRIVER
    employee_id: Optional[int] = None       # null clears the slot
    remarks: Optional[str] = None
    chk_r = field_validator("crew_role")(_in(CrewRole.ALL))


class AssignmentsIn(BaseModel):
    """A grid save: several cells at once, so keyboard entry across a row is one request."""
    cells: list[AssignmentIn] = Field(min_length=1)


class PatternIn(BaseModel):
    pattern_code: str = Field(min_length=1, max_length=30)
    pattern_name: Optional[str] = None
    cycle_days: int = Field(default=7, ge=1, le=90)
    is_active: bool = True


class PatternSlotIn(BaseModel):
    cycle_day: int = Field(ge=0, le=89)
    schedule_id: Optional[int] = None        # empty = an off day in the cycle
    shift_number: Optional[int] = None
    crew_role: str = CrewRole.DRIVER
    chk_r = field_validator("crew_role")(_in(CrewRole.ALL))


class PatternSlotsIn(BaseModel):
    slots: list[PatternSlotIn] = []


class PatternMembersIn(BaseModel):
    employee_ids: list[int] = []


class GenerateIn(BaseModel):
    pattern_id: int
    anchor: Optional[dt.date] = None          # the date cycle day 0 falls on (default: period start)
    date_from: Optional[dt.date] = None
    date_to: Optional[dt.date] = None
    overwrite: bool = False                   # replace cells filled by hand as well


class PublishRosterIn(BaseModel):
    change_reason: Optional[str] = None
    acknowledge_warnings: bool = False


class NewRosterVersionIn(BaseModel):
    change_reason: Optional[str] = None


class OpenDayIn(BaseModel):
    duty_date: dt.date


class CloseDayIn(BaseModel):
    duty_date: dt.date
    force: bool = False


class ReopenDayIn(BaseModel):
    duty_date: dt.date
    reason: str = Field(min_length=1)


class DutyHandoverIn(BaseModel):
    """The driver stops part-way and somebody else finishes the duty."""
    at_day_offset: int = Field(default=0, ge=0, le=3)
    at_time: dt.time
    employee_id: Optional[int] = None        # null = nobody continued the duty
    reason_id: Optional[int] = None
    handover_reason: Optional[str] = None


class DutyActualIn(BaseModel):
    status: str = "AS_PLANNED"
    actual_employee_id: Optional[int] = None
    reason_id: Optional[int] = None
    remarks: Optional[str] = None
    chk_s = field_validator("status")(_in(DutyActualStatus.ALL))


class ExtraIn(BaseModel):
    """A spare or shunting duty on one day. Several a day is normal."""
    duty_date: dt.date
    duty_type: str = DutyType.SPARE
    crew_role: str = CrewRole.DRIVER
    employee_id: Optional[int] = None
    start_time: Optional[dt.time] = None
    end_time: Optional[dt.time] = None
    remarks: Optional[str] = None
    chk_t = field_validator("duty_type")(_in(DutyType.ALL))
    chk_r = field_validator("crew_role")(_in(CrewRole.ALL))


class ExtraUpdateIn(BaseModel):
    employee_id: Optional[int] = None
    start_time: Optional[dt.time] = None
    end_time: Optional[dt.time] = None
    remarks: Optional[str] = None


class RepeatBlockIn(BaseModel):
    """Repeat a block of days across the rest of the period (the first week, by default)."""
    source_from: Optional[dt.date] = None
    day_count: int = Field(default=7, ge=1, le=31)


class CopyDaysIn(BaseModel):
    source_from: dt.date
    target_from: dt.date
    day_count: int = Field(ge=1, le=31)


class SettingsIn(BaseModel):
    values: dict


# ---- schedules ----------------------------------------------------------
class ScheduleCloneIn(BaseModel):
    """A copy of an existing schedule, as a new draft."""
    schedule_code: str = Field(min_length=1, max_length=30)
    schedule_name: str = Field(min_length=1)
    vehicle_id: int
    effective_from: dt.date
    effective_to: Optional[dt.date] = None
    copy_from_version_id: Optional[int] = None      # which version to copy; the one in force by default

    @model_validator(mode="after")
    def _dates(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class ScheduleIn(BaseModel):
    schedule_code: str = Field(min_length=1, max_length=30)
    schedule_name: str = Field(min_length=1)
    vehicle_id: int
    recurrence_type: Literal["DAILY"] = "DAILY"
    effective_from: dt.date
    effective_to: Optional[dt.date] = None
    timezone: str = "Asia/Kolkata"

    @model_validator(mode="after")
    def _dates(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from")
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(self.timezone)
        except Exception:
            raise ValueError("unknown timezone")
        return self


class ScheduleUpdate(BaseModel):
    schedule_name: Optional[str] = None
    effective_from: Optional[dt.date] = None
    effective_to: Optional[dt.date] = None
    status: Optional[Literal["RETIRED"]] = None


class VersionIn(BaseModel):
    valid_from: dt.date
    valid_to: Optional[dt.date] = None
    change_reason: Optional[str] = None
    copy_from_version_id: Optional[int] = None

    @model_validator(mode="after")
    def _dates(self):
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be before valid_from")
        return self


class VersionUpdate(BaseModel):
    valid_from: Optional[dt.date] = None
    valid_to: Optional[dt.date] = None
    change_reason: Optional[str] = None


class ShiftIn(BaseModel):
    shift_name: str = Field(min_length=1, max_length=40)
    start_day_offset: int = Field(default=0, ge=0)
    start_time: dt.time
    end_day_offset: int = Field(default=0, ge=0)
    end_time: dt.time
    change_location_id: Optional[int] = None


class CrewConfigIn(BaseModel):
    crew_mode: str = CrewMode.SINGLE
    conductor_required: bool = False
    shifts: list[ShiftIn] = []
    chk_m = field_validator("crew_mode")(_in(CrewMode.ALL))


class PublishIn(BaseModel):
    change_reason: Optional[str] = None
    acknowledge_warnings: bool = False


class StopTimeIn(BaseModel):
    route_stop_id: int
    stop_sequence: int = Field(gt=0)
    arrival_day_offset: Optional[int] = Field(default=None, ge=0)
    scheduled_arrival_time: Optional[dt.time] = None
    departure_day_offset: Optional[int] = Field(default=None, ge=0)
    scheduled_departure_time: Optional[dt.time] = None
    planned_soc_pct: Pct = None
    chk_s = field_validator("planned_soc_pct")(_pct)


class TripIn(BaseModel):
    trip_number: str = Field(min_length=1, max_length=30)
    route_id: int
    direction_id: int
    planned_distance_km: Decimal = Field(gt=0)
    planned_start_soc_pct: Pct = None
    planned_end_soc_pct: Pct = None
    stops: list[StopTimeIn] = []
    chk_s = field_validator("planned_start_soc_pct", "planned_end_soc_pct")(_pct)


class MovementIn(BaseModel):
    movement_purpose: str
    planned_distance_km: Decimal = Field(default=Decimal(0), ge=0)
    planned_start_soc_pct: Pct = None
    planned_end_soc_pct: Pct = None
    payability_status: str = Payability.TO_BE_CONFIRMED
    payment_basis: str = PaymentBasis.UNSPECIFIED
    chk_p = field_validator("movement_purpose")(_in(MovementPurpose.ALL))
    chk_y = field_validator("payability_status")(_in(Payability.ALL))
    chk_b = field_validator("payment_basis")(_in(PaymentBasis.ALL))
    chk_s = field_validator("planned_start_soc_pct", "planned_end_soc_pct")(_pct)


class ChargingIn(BaseModel):
    charging_location_id: int
    planned_start_soc_pct: Pct = None
    planned_end_soc_pct: Pct = None
    expected_energy_kwh: Optional[Decimal] = Field(default=None, ge=0)
    chk_s = field_validator("planned_start_soc_pct", "planned_end_soc_pct")(_pct)


class LayoverIn(BaseModel):
    location_id: int
    layover_purpose: str = LayoverPurpose.OTHER
    planned_start_soc_pct: Pct = None
    planned_end_soc_pct: Pct = None
    chk_p = field_validator("layover_purpose")(_in(LayoverPurpose.ALL))
    chk_s = field_validator("planned_start_soc_pct", "planned_end_soc_pct")(_pct)


class HaltIn(BaseModel):
    location_id: int
    planned_start_soc_pct: Pct = None
    planned_end_soc_pct: Pct = None
    chk_s = field_validator("planned_start_soc_pct", "planned_end_soc_pct")(_pct)


class ActivityIn(BaseModel):
    sequence_number: Optional[int] = Field(default=None, gt=0)
    activity_type: str
    origin_location_id: int
    destination_location_id: int
    start_day_offset: int = Field(default=0, ge=0)
    scheduled_start_time: dt.time
    end_day_offset: int = Field(default=0, ge=0)
    scheduled_end_time: dt.time
    remarks: Optional[str] = None
    trip: Optional[TripIn] = None
    movement: Optional[MovementIn] = None
    charging: Optional[ChargingIn] = None
    layover: Optional[LayoverIn] = None
    halt: Optional[HaltIn] = None
    chk_t = field_validator("activity_type")(_in(ActivityType.ALL))

    @model_validator(mode="after")
    def _detail_matches_type(self):
        want = {
            ActivityType.PASSENGER_TRIP: "trip",
            ActivityType.NON_REVENUE_MOVEMENT: "movement",
            ActivityType.CHARGING: "charging",
            ActivityType.LAYOVER: "layover",
            ActivityType.HALT: "halt",
        }[self.activity_type]
        for name in ("trip", "movement", "charging", "layover", "halt"):
            if name == want and getattr(self, name) is None:
                raise ValueError(f"{want} details are required for {self.activity_type}")
            if name != want and getattr(self, name) is not None:
                raise ValueError(f"{name} details not allowed for {self.activity_type}")
        return self


class ReorderIn(BaseModel):
    activity_ids: list[int]


# ---- trip sheets --------------------------------------------------------
class TripSheetCreate(BaseModel):
    schedule_id: int
    operating_date: dt.date


class TripStopIn(BaseModel):
    scheduled_stop_time_id: int
    arrival_day_offset: Optional[int] = Field(default=None, ge=0)
    arrival_time: Optional[dt.time] = None
    departure_day_offset: Optional[int] = Field(default=None, ge=0)
    departure_time: Optional[dt.time] = None
    odometer_km: Optional[Decimal] = Field(default=None, ge=0)
    soc_pct: Pct = None
    chk_s = field_validator("soc_pct")(_pct)


class TripRowIn(BaseModel):
    row_id: int
    status: str = RowStatus.PENDING
    actual_start_day_offset: Optional[int] = Field(default=None, ge=0)
    actual_start_time: Optional[dt.time] = None
    actual_end_day_offset: Optional[int] = Field(default=None, ge=0)
    actual_end_time: Optional[dt.time] = None
    start_odometer_km: Optional[Decimal] = Field(default=None, ge=0)
    end_odometer_km: Optional[Decimal] = Field(default=None, ge=0)
    start_soc_pct: Pct = None
    end_soc_pct: Pct = None
    energy_kwh: Optional[Decimal] = Field(default=None, ge=0)
    stopped_at_route_stop_id: Optional[int] = None
    reason_id: Optional[int] = None
    attributable_to: Optional[str] = None
    remarks: Optional[str] = None
    extra_from_location_id: Optional[int] = None
    extra_to_location_id: Optional[int] = None
    extra_payable: bool = False
    stops: Optional[list[TripStopIn]] = None        # None = leave stop details unchanged
    chk_st = field_validator("status")(_in(RowStatus.ALL))
    chk_s = field_validator("start_soc_pct", "end_soc_pct")(_pct)

    @field_validator("attributable_to")
    @classmethod
    def _a(cls, v):
        return v if v is None else _in(Attribution.ALL)(v)


class TripCrewIn(BaseModel):
    crew_id: int
    employee_id: Optional[int] = None
    duty_start_day_offset: Optional[int] = Field(default=None, ge=0)
    duty_start_time: Optional[dt.time] = None
    duty_end_day_offset: Optional[int] = Field(default=None, ge=0)
    duty_end_time: Optional[dt.time] = None
    handover_reason: Optional[str] = None


class TripSheetSave(BaseModel):
    paper_sheet_no: Optional[str] = Field(default=None, max_length=40)
    paper_version_number: Optional[int] = Field(default=None, ge=1)
    bus_change_registration: Optional[str] = Field(default=None, max_length=20)
    bus_change_from_row_id: Optional[int] = None
    bus_change_reason_id: Optional[int] = None
    remarks: Optional[str] = None
    rows: list[TripRowIn] = []
    crew: list[TripCrewIn] = []


class CrewAddIn(BaseModel):
    crew_role: str
    chk_r = field_validator("crew_role")(_in(CrewRole.ALL))


class HandoverIn(BaseModel):
    at_day_offset: int = Field(default=0, ge=0)
    at_time: dt.time
    employee_id: Optional[int] = None
    reason: str = Field(min_length=1)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=3)


class TripReasonIn(BaseModel):
    reason_code: str = Field(min_length=1, max_length=30)
    reason_name: str = Field(min_length=1, max_length=150)
    reason_name_local: Optional[str] = Field(default=None, max_length=150)
    default_attributable_to: str = Attribution.OPERATOR
    is_active: bool = True
    chk_a = field_validator("default_attributable_to")(_in(Attribution.ALL))
