from sqlalchemy.orm import Session

from app.models.models import CostCenterSetting

# key -> (default, description). Values are stored as strings.
DEFAULTS = {
    "require_stop_soc": ("false", "Planned SOC mandatory at every passenger stop"),
    "distance_tolerance_pct": ("2", "Allowed % difference between trip distance and route distance"),
    "gap_warn_minutes": ("30", "Warn when the gap between consecutive activities exceeds this"),
    "odometer_tolerance_pct": ("10", "Trip sheets: warn when odometer km differ from planned km by more than this"),
    "bill_lost_km_attributable_to": ("CLIENT", "Trip sheets: km lost to cancelled or cut-short runs are still billed "
                                               "when attributable to"),
}
LIST_KEYS = {"bill_lost_km_attributable_to": ("OPERATOR", "CLIENT", "EXTERNAL")}
CHOICE_KEYS: dict[str, tuple] = {}
# The printed language moved to the company and the cost center (see print_language on each), so that
# a depot that prints in another language is set up where the depot itself is set up.


def get_all(db: Session, cost_center_id: int | None) -> dict:
    stored = {s.key: s.value for s in db.query(CostCenterSetting).filter(CostCenterSetting.cost_center_id == cost_center_id)}
    return {k: stored.get(k, d[0]) for k, d in DEFAULTS.items()}


def update(db: Session, cost_center_id: int, values: dict) -> dict:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown setting: {key}")
        v = str(value).lower() if isinstance(value, bool) else str(value)
        if key in CHOICE_KEYS:
            if v not in CHOICE_KEYS[key]:
                raise ValueError(f"{key} must be one of {', '.join(x or 'none' for x in CHOICE_KEYS[key])}")
        elif key in LIST_KEYS:
            items = [x.strip().upper() for x in (value if isinstance(value, list) else v.split(",")) if x.strip()]
            if any(x not in LIST_KEYS[key] for x in items):
                raise ValueError(f"{key} must be a list of {', '.join(LIST_KEYS[key])}")
            v = ",".join(dict.fromkeys(items))
        elif DEFAULTS[key][0] in ("true", "false") and v not in ("true", "false"):
            raise ValueError(f"{key} must be true or false")
        elif DEFAULTS[key][0] not in ("true", "false") and float(v) < 0:
            raise ValueError(f"{key} must be non-negative")
        row = db.get(CostCenterSetting, (cost_center_id, key))
        if row:
            row.value = v
        else:
            db.add(CostCenterSetting(cost_center_id=cost_center_id, key=key, value=v))
    db.flush()
    return get_all(db, cost_center_id)
