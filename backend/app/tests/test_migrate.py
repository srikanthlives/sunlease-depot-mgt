"""The rebuild migrations: a changed table shape must not cost a row."""
from sqlalchemy import inspect, text

from app.db.session import engine
from app.migrate import _rebuild_with_rows

OLD_SHAPE = """
CREATE TABLE duty_actuals (
    actual_id INTEGER NOT NULL PRIMARY KEY,
    roster_id INTEGER NOT NULL,
    duty_date DATE NOT NULL,
    duty_type VARCHAR(10) NOT NULL,
    schedule_id INTEGER,
    shift_id INTEGER,
    slot_index INTEGER NOT NULL,
    crew_role VARCHAR(12) NOT NULL,
    planned_employee_id INTEGER,
    actual_employee_id INTEGER,
    status VARCHAR(14) NOT NULL,
    reason_id INTEGER,
    remarks TEXT,
    roster_version_id INTEGER,
    recorded_by INTEGER,
    recorded_at DATETIME,
    start_time TIME,
    end_time TIME,
    CONSTRAINT uq_duty_actual UNIQUE (roster_id, duty_date, duty_type, schedule_id, shift_id,
                                     crew_role, slot_index)
)
"""


def _a_roster() -> int:
    """A real roster row, so the rebuilt table's foreign keys are satisfied."""
    with engine.begin() as c:
        c.execute(text("INSERT INTO duty_rosters (cost_center_id, roster_code, period_from, "
                       "period_to, created_at, updated_at) VALUES (1, 'MIG', '2026-10-01', "
                       "'2026-10-31', '2026-10-01', '2026-10-01')"))
        return c.execute(text("SELECT roster_id FROM duty_rosters WHERE roster_code = 'MIG'")).scalar()


def _make_old_table(rows: int) -> None:
    """Put the pre-segment shape back, with its own index, as an older database would have it."""
    roster_id = _a_roster()
    with engine.begin() as c:
        for op in ("insert", "update", "delete"):
            c.execute(text(f"DROP TRIGGER IF EXISTS lock_duty_actuals_{op}"))
        c.execute(text("DROP TABLE IF EXISTS duty_actuals"))
        c.execute(text("DROP TABLE IF EXISTS duty_actuals__old"))
        c.execute(text(OLD_SHAPE))
        c.execute(text("CREATE INDEX ix_duty_actual_date ON duty_actuals (roster_id, duty_date)"))
        for i in range(rows):
            c.execute(text(
                "INSERT INTO duty_actuals (actual_id, roster_id, duty_date, duty_type, slot_index,"
                " crew_role, status, start_time, remarks) "
                "VALUES (:i, :roster, '2026-10-23', 'SCHEDULE', 0, 'DRIVER', 'AS_PLANNED', "
                "'06:00', :r)"), {"i": i + 1, "roster": roster_id, "r": f"row {i + 1}"})


def test_rebuild_carries_every_row_across(db):
    _make_old_table(3)
    _rebuild_with_rows("duty_actuals", "segment",
                       {"duty_start_time": "start_time", "duty_end_time": "end_time"})

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("duty_actuals")}
    assert "segment" in columns and "duty_start_time" in columns
    assert "start_time" not in columns                      # renamed, not duplicated
    assert not inspector.has_table("duty_actuals__old")     # the stash is cleaned up

    with engine.begin() as c:
        rows = c.execute(text("SELECT actual_id, segment, duty_start_time, remarks "
                              "FROM duty_actuals ORDER BY actual_id")).all()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert {r[1] for r in rows} == {0}                      # existing rows become segment 0
    assert [r[3] for r in rows] == ["row 1", "row 2", "row 3"]
    assert rows[0][2] is not None                           # the old start_time came across


def test_rebuild_is_a_no_op_once_done(db):
    _make_old_table(2)
    for _ in range(3):
        _rebuild_with_rows("duty_actuals", "segment",
                           {"duty_start_time": "start_time", "duty_end_time": "end_time"})
    with engine.begin() as c:
        assert c.execute(text("SELECT COUNT(*) FROM duty_actuals")).scalar() == 2


def test_a_failed_rebuild_is_finished_on_the_next_run(db):
    """A run that dies after the rename must not leave the rows stranded."""
    _make_old_table(2)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE duty_actuals RENAME TO duty_actuals__old"))
        c.execute(text("DROP INDEX IF EXISTS ix_duty_actual_date"))
    assert inspect(engine).has_table("duty_actuals__old")

    _rebuild_with_rows("duty_actuals", "segment",
                       {"duty_start_time": "start_time", "duty_end_time": "end_time"})
    with engine.begin() as c:
        assert c.execute(text("SELECT COUNT(*) FROM duty_actuals")).scalar() == 2
    assert not inspect(engine).has_table("duty_actuals__old")
