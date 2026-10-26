"""Additive auto-migration (no Alembic), same approach as sunlease-hrms1.

Creates missing tables, adds missing columns, and (on SQLite) installs the
triggers that make published schedule content immutable even when the API
is bypassed. Safe to run repeatedly; called on every startup.

    python -m app.migrate
"""
from sqlalchemy import inspect, text

from app.db.session import Base, engine
import app.models  # noqa: F401


def _add_column_ddl(table_name: str, column) -> str:
    parts = [f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}']
    if column.default is not None and getattr(column.default, "is_scalar", False):
        parts.append(f"DEFAULT {column.default.arg!r}")
    return " ".join(parts)


# Tables whose rows belong to a version (directly or via activity).
_VERSION_OF = {
    "scheduled_activities": "NEW.schedule_version_id",
    "scheduled_trips": "NEW.schedule_version_id",
    "schedule_shifts": "NEW.schedule_version_id",
}
_ACTIVITY_CHILDREN = ["scheduled_stop_times", "scheduled_movements", "scheduled_charging", "scheduled_layovers",
                      "scheduled_halts"]

# Columns removed from the models; dropped from existing databases on start.
# Planned odometer readings were dropped on 21-Oct-2026: schedules carry planned km only.
_DROPPED_COLUMNS = {
    "scheduled_trips": ["planned_start_odometer_km", "planned_end_odometer_km"],
    "scheduled_movements": ["planned_start_odometer_km", "planned_end_odometer_km"],
    "scheduled_stop_times": ["planned_odometer_km"],
}
# Detail-level remarks dropped on 21-Oct-2026: never editable, the activity's own remarks are used instead.
for _t in ("scheduled_movements", "scheduled_charging", "scheduled_layovers", "scheduled_halts"):
    _DROPPED_COLUMNS.setdefault(_t, []).append("remarks")
# Tables replaced by others; dropped after backfill_tenancy has copied what it needs.
_DROPPED_TABLES = ["app_settings"]   # -> cost_center_settings


def _lock_trigger_sql() -> list[str]:
    """Reject INSERT/UPDATE/DELETE on schedule content unless its version is DRAFT."""
    stmts = []
    not_draft = "(SELECT status FROM schedule_versions WHERE schedule_version_id = {vid}) <> 'DRAFT'"
    msg = "RAISE(ABORT, 'schedule version is not a draft: published content is immutable')"
    for table, vid_new in _VERSION_OF.items():
        vid_old = vid_new.replace("NEW", "OLD")
        for op, vid in (("INSERT", vid_new), ("UPDATE", vid_old), ("DELETE", vid_old)):
            stmts.append(
                f"CREATE TRIGGER IF NOT EXISTS lock_{table}_{op.lower()} BEFORE {op} ON {table} "
                f"WHEN {not_draft.format(vid=vid)} BEGIN SELECT {msg}; END"
            )
    act_ver = "(SELECT schedule_version_id FROM scheduled_activities WHERE activity_id = {aid})"
    for table in _ACTIVITY_CHILDREN:
        for op, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
            vid = act_ver.format(aid=f"{ref}.activity_id")
            stmts.append(
                f"CREATE TRIGGER IF NOT EXISTS lock_{table}_{op.lower()} BEFORE {op} ON {table} "
                f"WHEN {not_draft.format(vid=vid)} BEGIN SELECT {msg}; END"
            )
    # trip sheets: rows, stops and crew are frozen while the sheet is APPROVED
    approved = "(SELECT status FROM trip_sheets WHERE sheet_id = {sid}) = 'APPROVED'"
    msg2 = "RAISE(ABORT, 'trip sheet is approved: reopen it before changing it')"
    row_sheet = "(SELECT sheet_id FROM trip_sheet_rows WHERE row_id = {rid})"
    for table, sid_expr in (("trip_sheet_rows", "{ref}.sheet_id"), ("trip_sheet_crew", "{ref}.sheet_id"),
                            ("trip_sheet_stops", row_sheet.format(rid="{ref}.row_id"))):
        for op, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
            sid = sid_expr.format(ref=ref)
            stmts.append(
                f"CREATE TRIGGER IF NOT EXISTS lock_{table}_{op.lower()} BEFORE {op} ON {table} "
                f"WHEN {approved.format(sid=sid)} BEGIN SELECT {msg2}; END"
            )
    # duty roster: planned assignments are frozen once their version is published
    r_draft = ("(SELECT status FROM duty_roster_versions WHERE roster_version_id = {vid}) <> 'DRAFT'")
    msg3 = "RAISE(ABORT, 'roster version is not a draft: published assignments are immutable')"
    for op, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
        stmts.append(
            f"CREATE TRIGGER IF NOT EXISTS lock_duty_assignments_{op.lower()} BEFORE {op} ON duty_assignments "
            f"WHEN {r_draft.format(vid=f'{ref}.roster_version_id')} BEGIN SELECT {msg3}; END"
        )
    for op, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
        stmts.append(
            f"CREATE TRIGGER IF NOT EXISTS lock_duty_extras_{op.lower()} BEFORE {op} ON duty_extras "
            f"WHEN {r_draft.format(vid=f'{ref}.roster_version_id')} BEGIN SELECT {msg3}; END"
        )
    # duty roster: a closed day's actuals are frozen (reopen the day to change them)
    closed = ("{ref}.duty_date <= COALESCE((SELECT locked_through FROM duty_rosters "
              "WHERE roster_id = {ref}.roster_id), '0001-01-01')")
    msg4 = "RAISE(ABORT, 'duty day is closed: reopen it before changing it')"
    for op, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
        stmts.append(
            f"CREATE TRIGGER IF NOT EXISTS lock_duty_actuals_{op.lower()} BEFORE {op} ON duty_actuals "
            f"WHEN {closed.format(ref=ref)} BEGIN SELECT {msg4}; END"
        )
    return stmts


def migrate(verbose: bool = False) -> None:
    Base.metadata.create_all(bind=engine)
    # a column that stopped being NOT NULL, and a changed UNIQUE constraint, cannot be ALTERed in
    # SQLite, so these tables are rebuilt first - afterwards the add-column loop would mask the
    # difference. Rows are carried across, never dropped.
    _rebuild_nullable("duty_actuals", "schedule_id", verbose)
    _rebuild_with_rows("duty_actuals", "segment", {"duty_start_time": "start_time",
                                                   "duty_end_time": "end_time"}, verbose)
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        live = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in live:
                with engine.begin() as conn:
                    conn.execute(text(_add_column_ddl(table.name, column)))
                if verbose:
                    print(f"[MIGRATE] added {table.name}.{column.name}")
    for table_name, columns in _DROPPED_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        live = {c["name"] for c in inspector.get_columns(table_name)}
        for name in columns:
            if name in live:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE "{table_name}" DROP COLUMN "{name}"'))
                print(f"[MIGRATE] dropped {table_name}.{name}")
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            for stmt in _lock_trigger_sql():
                conn.execute(text(stmt))
    from app.db.session import SessionLocal
    from app.services.org_service import backfill_tenancy
    with SessionLocal() as db:
        backfill_tenancy(db, verbose)
        _move_print_language(db, verbose)
    for name in _DROPPED_TABLES:
        if inspect(engine).has_table(name):
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE "{name}"'))
            print(f"[MIGRATE] dropped table {name}")


def _rebuild_nullable(table_name: str, column_name: str, verbose: bool = False) -> None:
    """Recreate a table whose column stopped being NOT NULL - something SQLite cannot ALTER.

    Only ever done while the table is EMPTY. With rows in it the table is left alone and a
    warning is printed, because dropping it would lose them.
    """
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    live = {c["name"]: c for c in inspector.get_columns(table_name)}
    column = live.get(column_name)
    if column is None or column["nullable"]:
        return
    with engine.begin() as conn:
        rows = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
    if rows:
        print(f"[MIGRATE] {table_name} needs rebuilding but holds {rows} row(s): left alone")
        return
    with engine.begin() as conn:
        for trigger in ("insert", "update", "delete"):
            conn.execute(text(f"DROP TRIGGER IF EXISTS lock_{table_name}_{trigger}"))
        conn.execute(text(f'DROP TABLE "{table_name}"'))
    Base.metadata.tables[table_name].create(bind=engine)
    if verbose:
        print(f"[MIGRATE] rebuilt empty table {table_name}")


def _rebuild_with_rows(table_name: str, expected_column: str, renamed: dict[str, str],
                       verbose: bool = False) -> None:
    """Rebuild a table whose UNIQUE constraint changed, keeping its rows.

    SQLite cannot alter a table-level constraint, so the table is renamed aside, recreated from
    the models, and its rows copied back. `renamed` maps a new column name to the old one it
    takes its values from; every other column is copied where both shapes have it.

    Everything happens in one transaction, and the stash is dropped only once the row counts
    match, so a failure leaves the original table untouched. If an earlier attempt did fail
    part-way, the leftover stash is found and finished on the next run rather than left behind.
    """
    inspector = inspect(engine)
    stash = f"{table_name}__old"
    # a previous run may have renamed the table and died before recreating it, so the stash
    # decides as much as the table itself does
    resuming = inspector.has_table(stash)
    if not inspector.has_table(table_name) and not resuming:
        return
    if resuming:
        old_columns = {c["name"] for c in inspector.get_columns(stash)}
    else:
        old_columns = {c["name"] for c in inspector.get_columns(table_name)}
        if expected_column in old_columns:
            return

    table = Base.metadata.tables[table_name]
    # each new column either takes an old column's values, or - when it is new and NOT NULL -
    # its model default as a literal, because a plain INSERT..SELECT does not run Python defaults
    pairs = []
    for c in table.columns:
        source = renamed.get(c.name, c.name)
        if source in old_columns:
            pairs.append((c.name, f'"{source}"'))
        elif not c.nullable and c.default is not None and getattr(c.default, "is_scalar", False):
            pairs.append((c.name, repr(c.default.arg)))
        elif not c.nullable and not c.primary_key:
            raise RuntimeError(f"{table_name}.{c.name} is NOT NULL with no default: "
                               "a rebuild cannot invent a value for the existing rows")

    with engine.begin() as conn:
        if not resuming:
            rows = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
            for op in ("insert", "update", "delete"):
                conn.execute(text(f"DROP TRIGGER IF EXISTS lock_{table_name}_{op}"))
            conn.execute(text(f'ALTER TABLE "{table_name}" RENAME TO "{stash}"'))
            # SQLite keeps an index's name when its table is renamed, so the old indexes would
            # collide with the ones the new table brings
            for (index_name,) in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :t "
                    "AND name NOT LIKE 'sqlite_autoindex%'"), {"t": stash}).all():
                conn.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
        else:
            rows = conn.execute(text(f'SELECT COUNT(*) FROM "{stash}"')).scalar()
            if inspector.has_table(table_name):
                conn.execute(text(f'DROP TABLE "{table_name}"'))

        table.create(bind=conn)
        if rows:
            into = ", ".join(f'"{name}"' for name, _ in pairs)
            frm = ", ".join(expr for _, expr in pairs)
            conn.execute(text(f'INSERT INTO "{table_name}" ({into}) SELECT {frm} FROM "{stash}"'))
            copied = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
            if copied != rows:          # never lose a row to a rebuild
                raise RuntimeError(f"{table_name}: copied {copied} of {rows} rows, rolling back")
        conn.execute(text(f'DROP TABLE "{stash}"'))
    if verbose or rows:
        print(f"[MIGRATE] rebuilt {table_name} for its new unique key, {rows} row(s) carried over")


def _move_print_language(db, verbose: bool = False) -> None:
    """The printed language used to be a validation setting; it now lives on the cost center.

    Any value a depot had chosen is carried over once, and the old setting row is removed.
    """
    from app.models.models import CostCenter, CostCenterSetting
    rows = db.query(CostCenterSetting).filter(CostCenterSetting.key == "print_language").all()
    for row in rows:
        cc = db.get(CostCenter, row.cost_center_id)
        if cc is not None:
            cc.print_language = row.value
        db.delete(row)
    if rows:
        db.commit()
        if verbose:
            print(f"[MIGRATE] moved print_language onto {len(rows)} cost center(s)")


if __name__ == "__main__":
    migrate(verbose=True)
