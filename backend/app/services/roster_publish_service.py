"""Publishing a duty roster, and revising a published one.

The rules, as the depot set them out:

* Publishing freezes the version. Its assignments become immutable (the database enforces it,
  not only the API).
* A revision is a **new version covering the whole period**. Days already completed are copied
  across unchanged and stay locked, so only days from the change onward can differ.
* Exactly one version is live at a time: the latest published one. Earlier versions are kept
  only so a revision can be compared against what it replaced.
"""
import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import DutySource, RosterStatus
from app.models.models import DutyActual, DutyAssignment, DutyExtra, DutyRoster, DutyRosterVersion
from app.services import roster_service


def bad(status: int, msg: str):
    raise HTTPException(status, msg)


def publish(db: Session, roster: DutyRoster, version: DutyRosterVersion, user,
            change_reason: str | None, acknowledge_warnings: bool = False) -> dict:
    roster_service.assert_draft(version)
    result = roster_service.validate(db, roster, version)
    if result["errors"]:
        bad(409, f"{result['errors']} error(s) must be fixed before publishing")
    if result["warnings"] and not acknowledge_warnings:
        bad(409, f"{result['warnings']} warning(s): confirm them to publish")

    previous = roster_service.live_version(roster)
    if previous is not None:
        previous.prior_status = previous.status
        previous.status = RosterStatus.SUPERSEDED
        previous.superseded_by_version_id = version.roster_version_id

    version.status = RosterStatus.PUBLISHED
    version.published_at = dt.datetime.utcnow()
    version.published_by = user.id
    version.change_reason = change_reason or version.change_reason
    db.flush()
    return {"roster_version_id": version.roster_version_id, "version_number": version.version_number,
            "status": version.status, "superseded": previous.version_number if previous else None,
            "warnings": result["warnings"], "assignments": len(version.assignments),
            "extras": len(version.extras)}


def unpublish(db: Session, roster: DutyRoster, version: DutyRosterVersion, user) -> dict:
    """Take the live version back to draft. Refused once the roster has any history: a closed
    day or a recorded actual means the plan was already worked to."""
    if version.status != RosterStatus.PUBLISHED:
        bad(409, f"Version {version.version_number} is {version.status.lower()}, not published")
    if roster_service.live_version(roster) is not version:
        bad(409, "Only the live version can be unpublished")
    if roster.locked_through is not None:
        bad(409, f"Days are already closed up to {roster.locked_through:%d-%b-%Y}: "
                 "the published plan is part of the record")
    recorded = db.query(DutyActual).filter(DutyActual.roster_id == roster.roster_id).count()
    if recorded:
        bad(409, f"{recorded} duty day(s) have actuals recorded against this version")

    version.status = RosterStatus.DRAFT
    version.published_at = version.published_by = None
    # whatever this version superseded becomes live again
    restored = (db.query(DutyRosterVersion)
                .filter(DutyRosterVersion.superseded_by_version_id == version.roster_version_id)
                .all())
    for v in restored:
        v.status = v.prior_status or RosterStatus.PUBLISHED
        v.prior_status = None
        v.superseded_by_version_id = None
    db.flush()
    return {"roster_version_id": version.roster_version_id, "status": version.status,
            "restored": [v.version_number for v in restored]}


def new_version(db: Session, roster: DutyRoster, user, change_reason: str | None) -> DutyRosterVersion:
    """Start a revision: a draft copy of the whole live version.

    Every day is copied, completed ones included - they are marked `CARRIED` and the lock on
    closed days keeps them as they were, so a revision can only change what is still to come.
    """
    if roster_service.draft_version(roster) is not None:
        bad(409, "This roster already has a draft version")
    live = roster_service.live_version(roster)
    if live is None:
        bad(409, "Publish version 1 before revising it")

    nxt = max(v.version_number for v in roster.versions) + 1
    draft = DutyRosterVersion(roster_id=roster.roster_id, version_number=nxt,
                              status=RosterStatus.DRAFT, change_reason=change_reason,
                              created_by=user.id)
    db.add(draft)
    db.flush()

    locked = roster.locked_through
    for a in live.assignments:
        carried = bool(locked and a.duty_date <= locked)
        db.add(DutyAssignment(roster_version_id=draft.roster_version_id, duty_date=a.duty_date,
                              schedule_id=a.schedule_id, shift_id=a.shift_id, crew_role=a.crew_role,
                              employee_id=a.employee_id, remarks=a.remarks,
                              source=DutySource.CARRIED if carried else a.source))
    for x in live.extras:
        db.add(DutyExtra(roster_version_id=draft.roster_version_id, duty_date=x.duty_date,
                         duty_type=x.duty_type, crew_role=x.crew_role, slot_index=x.slot_index,
                         employee_id=x.employee_id, start_time=x.start_time, end_time=x.end_time,
                         remarks=x.remarks))
    db.flush()
    return draft


# --------------------------------------------------------------------------
# Comparing a revision against what it replaced
# --------------------------------------------------------------------------
def _assignment_map(version: DutyRosterVersion) -> dict:
    out = {}
    for a in version.assignments:
        shift_number = a.shift.shift_number if a.shift else None
        out[(a.duty_date, a.schedule_id, shift_number, a.crew_role)] = a
    return out


def _who(a) -> dict | None:
    if a is None or a.employee_id is None:
        return None
    return {"employee_id": a.employee_id, "employee_number": a.employee.employee_number,
            "employee_name": a.employee.full_name}


def diff(db: Session, roster: DutyRoster, base: DutyRosterVersion,
         other: DutyRosterVersion) -> dict:
    """What changed between two versions, changed slots only.

    Days inside the locked stretch are reported as carried over: a revision cannot alter them,
    so seeing them listed as 'unchanged' among real changes would only be noise.
    """
    a_map, b_map = _assignment_map(base), _assignment_map(other)
    locked = roster.locked_through
    rows = []
    for key in sorted(set(a_map) | set(b_map), key=lambda k: (k[0], str(k[1]), str(k[2]), k[3])):
        day, schedule_id, shift_number, crew_role = key
        before, after = _who(a_map.get(key)), _who(b_map.get(key))
        if (before or {}).get("employee_id") == (after or {}).get("employee_id"):
            continue
        sch = (a_map.get(key) or b_map.get(key)).schedule
        rows.append({
            "duty_date": day.isoformat(), "schedule_code": sch.schedule_code,
            "fleet_number": sch.vehicle.fleet_number, "shift_number": shift_number,
            "crew_role": crew_role, "before": before, "after": after,
            "locked": bool(locked and day <= locked),
            "change": "ADDED" if before is None else "REMOVED" if after is None else "REPLACED",
        })

    def extra_key(x):
        return (x.duty_date, x.duty_type, x.crew_role, x.slot_index)
    xa = {extra_key(x): x for x in base.extras}
    xb = {extra_key(x): x for x in other.extras}
    extra_rows = []
    for key in sorted(set(xa) | set(xb), key=lambda k: (k[0], k[1], k[2], k[3])):
        before, after = _who(xa.get(key)), _who(xb.get(key))
        if (before or {}).get("employee_id") == (after or {}).get("employee_id") and (
                (key in xa) == (key in xb)):
            continue
        extra_rows.append({"duty_date": key[0].isoformat(), "duty_type": key[1], "crew_role": key[2],
                           "slot_index": key[3], "before": before, "after": after,
                           "locked": bool(locked and key[0] <= locked),
                           "change": "ADDED" if key not in xa else "REMOVED" if key not in xb else "REPLACED"})

    carried = sum(1 for k, a in a_map.items() if locked and k[0] <= locked)
    return {
        "roster_id": roster.roster_id, "roster_code": roster.roster_code,
        "base": {"roster_version_id": base.roster_version_id, "version_number": base.version_number,
                 "status": base.status},
        "other": {"roster_version_id": other.roster_version_id, "version_number": other.version_number,
                  "status": other.status},
        "locked_through": roster.locked_through,
        "carried_over": carried,
        "changes": len(rows) + len(extra_rows),
        "rows": rows, "extras": extra_rows,
    }
