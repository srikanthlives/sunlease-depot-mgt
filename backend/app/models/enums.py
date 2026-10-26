"""String constants used as column values (kept as plain strings so the
schema stays portable and migrate.py never needs to alter enum types)."""


class Role:
    """Roles held per cost center (UserCostCenterRole). SUPER_ADMIN is a global user flag
    (User.role) that bypasses cost-center checks; every other user has User.role = USER."""
    ADMIN = "ADMIN"
    PUBLISHER = "PUBLISHER"
    SCHEDULER = "SCHEDULER"
    MIS = "MIS"            # clerk: enters and submits trip sheets, read-only elsewhere
    VIEWER = "VIEWER"
    ALL = (ADMIN, PUBLISHER, SCHEDULER, MIS, VIEWER)
    RANK = {VIEWER: 1, MIS: 2, SCHEDULER: 3, PUBLISHER: 4, ADMIN: 5}
    SUPER_ADMIN = "SUPER_ADMIN"
    USER = "USER"


class VehicleStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RETIRED = "RETIRED"
    ALL = (ACTIVE, INACTIVE, RETIRED)


class LocationType:
    DEPOT = "DEPOT"
    TERMINAL = "TERMINAL"
    BUS_STOP = "BUS_STOP"
    CHARGING_POINT = "CHARGING_POINT"
    OTHER = "OTHER"
    ALL = (DEPOT, TERMINAL, BUS_STOP, CHARGING_POINT, OTHER)


class ScheduleStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"
    ALL = (DRAFT, PUBLISHED, RETIRED)


class VersionStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ALL = (DRAFT, PUBLISHED, SUPERSEDED)


class ActivityType:
    PASSENGER_TRIP = "PASSENGER_TRIP"
    NON_REVENUE_MOVEMENT = "NON_REVENUE_MOVEMENT"
    CHARGING = "CHARGING"
    LAYOVER = "LAYOVER"
    # off-service block at a depot or night-halt terminal (parking, washing, charging,
    # maintenance - not timed separately); not counted in the cycle time
    HALT = "HALT"
    ALL = (PASSENGER_TRIP, NON_REVENUE_MOVEMENT, CHARGING, LAYOVER, HALT)


class MovementPurpose:
    DEPOT_POSITIONING = "DEPOT_POSITIONING"
    CHARGING_ACCESS = "CHARGING_ACCESS"
    RETURN_TO_SERVICE = "RETURN_TO_SERVICE"
    RETURN_TO_DEPOT = "RETURN_TO_DEPOT"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"
    ALL = (DEPOT_POSITIONING, CHARGING_ACCESS, RETURN_TO_SERVICE, RETURN_TO_DEPOT, MAINTENANCE, OTHER)


class Payability:
    PAYABLE = "PAYABLE"
    NON_PAYABLE = "NON_PAYABLE"
    TO_BE_CONFIRMED = "TO_BE_CONFIRMED"
    ALL = (PAYABLE, NON_PAYABLE, TO_BE_CONFIRMED)


class PaymentBasis:
    PER_KM = "PER_KM"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    INCLUDED_IN_CONTRACT = "INCLUDED_IN_CONTRACT"
    OTHER = "OTHER"
    UNSPECIFIED = "UNSPECIFIED"
    ALL = (PER_KM, FIXED_AMOUNT, INCLUDED_IN_CONTRACT, OTHER, UNSPECIFIED)


class LayoverPurpose:
    TERMINAL_RECOVERY = "TERMINAL_RECOVERY"
    INTER_TRIP = "INTER_TRIP"
    OVERNIGHT_PARKING = "OVERNIGHT_PARKING"
    OTHER = "OTHER"
    ALL = (TERMINAL_RECOVERY, INTER_TRIP, OVERNIGHT_PARKING, OTHER)


class StaffType:
    DRIVER = "DRIVER"
    CONDUCTOR = "CONDUCTOR"
    DEPOT_STAFF = "DEPOT_STAFF"
    ALL = (DRIVER, CONDUCTOR, DEPOT_STAFF)


class EmployeeSource:
    UPLOAD = "UPLOAD"
    HRMS = "HRMS"
    MANUAL = "MANUAL"


class CrewMode:
    SINGLE = "SINGLE"      # one driver (and conductor) for the whole day
    SHIFTS = "SHIFTS"      # shifts defined on the schedule version
    ALL = (SINGLE, SHIFTS)


class CrewRole:
    DRIVER = "DRIVER"
    CONDUCTOR = "CONDUCTOR"
    ALL = (DRIVER, CONDUCTOR)


class TripSheetStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ALL = (DRAFT, SUBMITTED, APPROVED)


class RowStatus:
    PENDING = "PENDING"        # not entered yet
    OPERATED = "OPERATED"
    PARTIAL = "PARTIAL"        # passenger trip cut short at a stop
    CANCELLED = "CANCELLED"
    ALL = (PENDING, OPERATED, PARTIAL, CANCELLED)


class Attribution:
    """Who caused lost km; each cost center decides which of these are still billed."""
    OPERATOR = "OPERATOR"
    CLIENT = "CLIENT"
    EXTERNAL = "EXTERNAL"      # traffic, road closure, police, weather
    ALL = (OPERATOR, CLIENT, EXTERNAL)


class RosterStatus:
    """A roster version's lifecycle. Only the latest PUBLISHED version is live; the
    rest are SUPERSEDED and kept only to compare what a revision changed."""
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ALL = (DRAFT, PUBLISHED, SUPERSEDED)


class DutySource:
    GENERATED = "GENERATED"    # produced by the duty pattern
    MANUAL = "MANUAL"          # set or changed by hand
    CARRIED = "CARRIED"        # copied from the previous version (a completed, locked day)
    ALL = (GENERATED, MANUAL, CARRIED)


class DutyActualStatus:
    AS_PLANNED = "AS_PLANNED"
    REPLACED = "REPLACED"          # somebody else worked the whole duty
    ABSENT = "ABSENT"              # nobody worked it
    NOT_OPERATED = "NOT_OPERATED"  # the duty did not happen (bus off road, trip cancelled)
    # a duty handed over part-way through: the first segment ends, the next one starts there
    HANDED_OVER = "HANDED_OVER"    # worked part of it, then had to stop
    TOOK_OVER = "TOOK_OVER"        # picked it up mid-duty
    ALL = (AS_PLANNED, REPLACED, ABSENT, NOT_OPERATED, HANDED_OVER, TOOK_OVER)


class AvailabilityStatus:
    """Depot-level marker of why an employee is not available; not HRMS leave approval."""
    WEEKLY_OFF = "WEEKLY_OFF"
    LEAVE = "LEAVE"
    SICK = "SICK"
    TRAINING = "TRAINING"
    OTHER = "OTHER"
    ALL = (WEEKLY_OFF, LEAVE, SICK, TRAINING, OTHER)


class DutyType:
    """A roster duty that is not tied to a schedule. Bus duties are DutyAssignment rows;
    these stand beside them, several per day if the depot wants."""
    SPARE = "SPARE"            # standby crew, not on a bus unless called in
    SHUNTING = "SHUNTING"      # moving buses about the depot (parking, washing, charging bays)
    ALL = (SPARE, SHUNTING)
