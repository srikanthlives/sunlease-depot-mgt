import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CalendarCheck, CheckCircle2, CornerDownRight, Download, Lock, LockOpen, PlayCircle, Split, Undo2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Modal, PageHeader, Spinner, Table } from "../components/ui";
import { Combobox, DateInput, Select, TextArea, TimeInput } from "../components/inputs";
import { fmtDate, label, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

const STATUS_TONE = {
  AS_PLANNED: "text-slate-600", REPLACED: "text-brand-700 font-medium",
  ABSENT: "text-rose-700 font-semibold", NOT_OPERATED: "text-slate-500",
};

/**
 * What actually happened, day by day, beside what was planned.
 *
 * The plan is never changed here. Opening a day copies the published plan into a record of its
 * own; the clerk then says who really worked each duty. Closing the day freezes that record and
 * stops any later version of the roster from altering the day.
 */
export default function DutyDay() {
  const { can } = useAuth();
  const toast = useToast();
  const { data: rosters = [] } = useApi("/rosters", []);
  const [rosterId, setRosterId] = useState(null);
  const [on, setOn] = useState(todayIso());
  const [day, setDay] = useState(null);
  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [edit, setEdit] = useState(null);
  const [reopen, setReopen] = useState(null);
  const [split, setSplit] = useState(null);
  const { data: reasons = [] } = useApi("/trip-reasons", []);
  const { data: crewData } = useApi(rosterId ? `/rosters/${rosterId}/crew-options` : null, null);

  const roster = useMemo(() => (rosters || []).find((r) => r.roster_id === rosterId), [rosters, rosterId]);

  useEffect(() => {
    if (rosterId || !(rosters || []).length) return;
    // the roster covering today, else the most recent one
    const today = todayIso();
    const match = rosters.find((r) => r.period_from <= today && r.period_to >= today);
    setRosterId((match || rosters[0]).roster_id);
    if (match) setOn(today < match.period_from ? match.period_from : today);
    else setOn(rosters[0].period_to);
  }, [rosters, rosterId]);

  const load = useCallback(async () => {
    if (!rosterId || !on) return;
    setLoading(true);
    try {
      const [d, b] = await Promise.all([
        client.get(`/rosters/${rosterId}/actuals/${on}`),
        client.get(`/rosters/${rosterId}/actuals`),
      ]);
      setDay(d.data);
      setBoard(b.data);
    } catch (e) {
      toast.error(apiErrorMessage(e));
      setDay(null);
    } finally {
      setLoading(false);
    }
  }, [rosterId, on]);                    // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const crewFor = (role) => (crewData?.crew || [])
    .filter((e) => e.staff_type === role && e.status === "ACTIVE")
    .map((e) => ({ value: e.employee_id, label: e.employee_name, sub: e.employee_number }));

  const openDay = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/actuals/open`, { duty_date: on });
      toast.ok(r.data.opened ? `${r.data.opened} duty slot(s) opened` : "Already open");
      setDay(r.data);
      load();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const saveRow = async () => {
    const body = { status: edit.status, actual_employee_id: edit.actual_employee_id,
                   reason_id: edit.reason_id, remarks: edit.remarks || null };
    try {
      const r = await client.put(`/rosters/${rosterId}/actuals/${edit.actual_id}`, body);
      setDay(r.data);
      setEdit(null);
      load();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  /** The driver stopped part-way: end their stretch and start the next one there. */
  const runSplit = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/actuals/${split.actual_id}/handover`, {
        at_day_offset: split.at_day_offset || 0, at_time: split.at_time,
        employee_id: split.employee_id, reason_id: split.reason_id,
        handover_reason: split.handover_reason || null,
      });
      toast.ok(`Duty handed over at ${r.data.at}`);
      setDay(r.data);
      setSplit(null);
      load();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const undoSplit = async (row) => {
    if (!window.confirm(`Undo the handover at ${row.from_time}? The duty goes back to whoever held it before.`)) return;
    try {
      const r = await client.delete(`/rosters/${rosterId}/actuals/${row.actual_id}/handover`);
      toast.ok("Handover removed");
      setDay(r.data);
      load();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const closeDay = async (force = false) => {
    try {
      const r = await client.post(`/rosters/${rosterId}/actuals/close`, { duty_date: on, force });
      toast.ok(`${fmtDate(on)} closed`);
      setDay(r.data);
      load();
    } catch (e) {
      const msg = apiErrorMessage(e);
      if (!force && msg.includes("confirm closing") && window.confirm(`${msg}\n\nClose the day as it stands?`)) {
        return closeDay(true);
      }
      toast.error(msg);
    }
  };

  const runReopen = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/actuals/reopen`,
        { duty_date: on, reason: reopen.reason });
      toast.ok(`${fmtDate(on)} reopened`);
      setDay(r.data);
      setReopen(null);
      load();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const counts = day?.counts || {};
  const check = day?.validation;
  /** Issues against the slot they belong to, so the clash shows on the row itself. */
  const rowIssues = useMemo(() => {
    const out = {};
    for (const i of check?.issues || []) {
      const row = (day?.rows || []).find((r) => r.schedule_code === i.schedule_code && r.slot_label === i.slot);
      if (!row) continue;
      if (!out[row.actual_id] || i.severity === "ERROR") out[row.actual_id] = i;
    }
    return out;
  }, [check, day]);
  const dayState = (board?.days || []).find((d) => d.duty_date === on);

  return (
    <>
      <PageHeader title="Duty day" subtitle="What actually happened, beside what was planned"
        actions={
          <div className="flex items-center gap-2">
            {day?.open && (
              <Button variant="secondary" icon={Download}
                onClick={() => window.open(`/api/reports/duty-day.xlsx?on=${on}`, "_blank")}>Excel</Button>
            )}
            {day && !day.open && can("MIS") && <Button icon={PlayCircle} onClick={openDay}>Open this day</Button>}
            {day?.open && !day.locked && can("PUBLISHER") && (
              <Button icon={Lock} onClick={() => closeDay(false)}>Close day</Button>
            )}
            {day?.locked && can("PUBLISHER") && (
              <Button variant="secondary" icon={LockOpen} onClick={() => setReopen({ reason: "" })}>Reopen</Button>
            )}
          </div>
        } />

      <Card className="mb-3">
        <div className="flex flex-wrap items-end gap-3">
          <Select label="Roster" className="w-64" value={rosterId || ""} onChange={(v) => setRosterId(Number(v))}
            options={(rosters || []).map((r) => ({ value: r.roster_id,
              label: `${r.roster_code} (${fmtDate(r.period_from)} to ${fmtDate(r.period_to)})` }))}
            placeholder="No rosters yet" />
          <DateInput label="Day" value={on} onChange={(v) => v && setOn(v)} />
          {roster && (
            <div className="text-xs text-slate-500">
              {roster.period_from <= on && on <= roster.period_to
                ? <>Period {fmtDate(roster.period_from)} – {fmtDate(roster.period_to)}</>
                : <span className="text-amber-700">That day is outside this roster's period</span>}
              {roster.locked_through && <> · closed through {fmtDate(roster.locked_through)}</>}
            </div>
          )}
        </div>

        {board && (
          <div className="mt-3 flex flex-wrap gap-1">
            {board.days.map((d) => (
              <button key={d.duty_date} onClick={() => setOn(d.duty_date)} title={
                d.locked ? "Closed" : d.open ? `${d.slots} slots, ${d.changed} changed` : "Not opened yet"}
                className={`rounded px-1.5 py-1 text-[11px] tabular-nums ${
                  d.duty_date === on ? "ring-2 ring-brand-400 " : ""}${
                  d.locked ? "bg-slate-200 text-slate-600"
                    : d.uncovered ? "bg-rose-100 text-rose-800"
                    : d.changed ? "bg-brand-50 text-brand-800"
                    : d.open ? "bg-emerald-50 text-emerald-800" : "bg-slate-50 text-slate-400"}`}>
                {d.duty_date.slice(8)}
              </button>
            ))}
          </div>
        )}
      </Card>

      {loading && <div className="py-10 text-center"><Spinner /></div>}

      {!loading && day && !day.open && (
        <Card>
          <p className="inline-flex items-center gap-2 text-sm text-slate-500">
            <CalendarCheck className="h-4 w-4" />
            {fmtDate(on)} has not been opened yet. Opening it copies the published plan for that day,
            and you then record who really worked each duty.
          </p>
        </Card>
      )}

      {!loading && day?.open && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[["Slots", day.slots, ""], ["As planned", counts.AS_PLANNED || 0, "text-slate-700"],
              ["Replaced", counts.REPLACED || 0, "text-brand-700"],
              ["Nobody worked it", counts.ABSENT || 0, "text-rose-700"],
              ["Not operated", counts.NOT_OPERATED || 0, "text-slate-500"]].map(([t, v, tone]) => (
              <div key={t} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">{t}</p>
                <p className={`text-lg font-semibold ${tone}`}>{v}</p>
              </div>
            ))}
          </div>

          {check && check.issues.length > 0 && (
            <Card className="mb-3" title={check.errors
              ? `${check.errors} error(s), ${check.warnings} warning(s) in today's record`
              : `${check.warnings} warning(s)`}>
              <ul className="max-h-48 space-y-1 overflow-auto text-xs">
                {check.issues.map((i, n) => (
                  <li key={n} className="flex items-start gap-2">
                    {i.severity === "ERROR"
                      ? <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-rose-700" />
                      : <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" />}
                    <span className="text-slate-600">{i.message}</span>
                  </li>
                ))}
              </ul>
              {check.errors > 0 && (
                <p className="mt-2 text-xs text-slate-500">
                  The day cannot be closed until these are put right - one of the two duties is
                  recorded against the wrong person.
                </p>
              )}
            </Card>
          )}
          {check && check.issues.length === 0 && (
            <p className="mb-3 inline-flex items-center gap-2 text-xs text-emerald-700">
              <CheckCircle2 className="h-3.5 w-3.5" /> Nobody is in two places at once, and everybody
              recorded was fit to be there.
            </p>
          )}

          <Card padded={false} title={`${fmtDate(on)}${day.locked ? " — closed" : ""}`}>
            <Table rowKey={(r) => r.actual_id} rows={day.rows}
              onRowClick={(r) => !day.locked && can("MIS") && setEdit({
                actual_id: r.actual_id, crew_role: r.crew_role, status: r.status,
                actual_employee_id: r.actual?.employee_id ?? null, reason_id: r.reason_id,
                remarks: r.remarks || "", planned: r.planned, slot: `${r.schedule_code} ${r.slot_label}` })}
              rowClassName={(r) => rowIssues[r.actual_id]?.severity === "ERROR" ? "bg-rose-50"
                : rowIssues[r.actual_id] ? "bg-amber-50" : ""}
              columns={[
                { key: "flag", title: "", className: "w-6", render: (r) => rowIssues[r.actual_id] && (
                  <AlertTriangle className={`h-3 w-3 ${rowIssues[r.actual_id].severity === "ERROR"
                    ? "text-rose-700" : "text-amber-600"}`} />
                ) },
                { key: "bus", title: "Bus / duty", render: (r) => (
                  <>
                    <span className="font-medium">{r.fleet_number || label(r.duty_type)}</span>
                    {r.schedule_code !== r.duty_type.charAt(0) + r.duty_type.slice(1).toLowerCase() && (
                      <span className="ml-1 text-xs text-slate-500">{r.schedule_code}</span>
                    )}
                  </>
                ) },
                { key: "slot_label", title: "Slot", className: "w-44", render: (r) => (
                  <>
                    <span className={r.took_over_from ? "pl-3" : ""}>
                      {r.took_over_from && <CornerDownRight className="mr-1 inline h-3 w-3 text-slate-400" />}
                      {r.slot_label}
                    </span>
                    {r.segments > 1 && r.from_time && (
                      <div className={`text-[11px] text-slate-500 ${r.took_over_from ? "pl-6" : ""}`}>
                        {r.from_time}–{r.to_time}{r.minutes != null ? ` · ${Math.round(r.minutes / 60 * 10) / 10}h` : ""}
                      </div>
                    )}
                    {r.called_out_to && (
                      <div className="text-[11px] text-brand-700">called out to {r.called_out_to}</div>
                    )}
                  </>
                ) },
                { key: "planned", title: "Planned", render: (r) => r.planned
                  ? <>{r.planned.employee_name}<span className="ml-1 font-mono text-xs text-slate-400">{r.planned.employee_number}</span></>
                  : <span className="text-slate-400">—</span> },
                { key: "arrow", title: "", className: "w-6", render: () => <ArrowRight className="h-3 w-3 text-slate-300" /> },
                { key: "actual", title: "Actual", render: (r) => r.actual
                  ? <>{r.actual.employee_name}<span className="ml-1 font-mono text-xs text-slate-400">{r.actual.employee_number}</span></>
                  : <span className="font-semibold text-rose-700">nobody</span> },
                { key: "status", title: "Status", className: "w-36",
                  render: (r) => <span className={STATUS_TONE[r.status]}>{label(r.status)}</span> },
                { key: "reason", title: "Reason", render: (r) => (
                  <>
                    {r.reason || (r.remarks ? <span className="text-xs text-slate-500">{r.remarks}</span>
                      : <span className="text-slate-300">—</span>)}
                    {r.handover_reason && (
                      <div className="text-[11px] text-slate-500">{r.handover_reason}</div>
                    )}
                  </>
                ) },
                { key: "x", title: "", className: "w-24 text-right", render: (r) => !day.locked && can("MIS") && (
                  <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
                    {r.duty_type !== "SPARE" && r.from_time && r.segments === r.segment + 1
                      && !["ABSENT", "NOT_OPERATED"].includes(r.status) && (
                      <button tabIndex={-1} title="The driver stopped part-way: hand the duty over"
                        className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
                        onClick={() => setSplit({ actual_id: r.actual_id, crew_role: r.crew_role,
                          at_time: "", at_day_offset: 0, employee_id: null, reason_id: null,
                          handover_reason: "", slot: `${r.schedule_code} ${r.slot_label}`,
                          from_time: r.from_time, to_time: r.to_time })}>
                        <Split className="h-3 w-3" /> Hand over
                      </button>
                    )}
                    {r.took_over_from && (
                      <button tabIndex={-1} title="Undo this handover"
                        className="inline-flex items-center text-xs text-slate-500 hover:text-rose-700"
                        onClick={() => undoSplit(r)}><Undo2 className="h-3 w-3" /></button>
                    )}
                  </span>
                ) },
              ]} />
          </Card>
        </>
      )}

      <p className="mt-2 text-xs text-slate-500">
        Click a row to record what happened. The status follows from who worked it: a different
        person is a replacement, nobody is an absence - and either needs a reason. Closing a day
        freezes its record and stops any later roster version from changing that day;
        reopening it needs a reason and unlocks every later day too.
        <b> Hand over</b> splits a duty when the driver had to stop part-way: their stretch ends at
        that time and whoever took over is recorded for the rest, each checked separately against
        the other duties of the day.
      </p>

      <Modal open={!!edit} title={edit ? `Record ${edit.slot}` : ""} onClose={() => setEdit(null)} onSave={saveRow}>
        {edit && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              Planned: <b>{edit.planned ? edit.planned.employee_name : "nobody"}</b>
            </p>
            <Select label="What happened" value={edit.status}
              onChange={(v) => setEdit({ ...edit, status: v,
                actual_employee_id: v === "NOT_OPERATED" || v === "ABSENT" ? null : edit.actual_employee_id })}
              options={[{ value: "AS_PLANNED", label: "Worked as planned" },
                        { value: "REPLACED", label: "Somebody else worked it" },
                        { value: "ABSENT", label: "Nobody worked it" },
                        { value: "NOT_OPERATED", label: "The duty did not happen" }]} />
            {edit.status !== "NOT_OPERATED" && edit.status !== "ABSENT" && (
              <Combobox label="Who worked it" options={crewFor(edit.crew_role)}
                value={edit.actual_employee_id} onChange={(v) => setEdit({ ...edit, actual_employee_id: v })} />
            )}
            <Select label="Reason" value={edit.reason_id || ""} placeholder="None"
              onChange={(v) => setEdit({ ...edit, reason_id: v ? Number(v) : null })}
              options={(reasons || []).filter((r) => r.is_active)
                .map((r) => ({ value: r.reason_id, label: r.reason_name }))} />
            <TextArea label="Remarks" value={edit.remarks}
              onChange={(e) => setEdit({ ...edit, remarks: e.target.value })} />
            <p className="text-xs text-slate-500">
              Anything other than "worked as planned" needs a reason code or a remark, so the
              end-of-day summary can say why.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!split} title={split ? `Hand over ${split.slot}` : ""}
        onClose={() => setSplit(null)} onSave={runSplit}>
        {split && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              The duty runs {split.from_time}–{split.to_time}. Whoever was driving stops at the time
              you give, and the person below finishes it.
            </p>
            <TimeInput label="Handed over at" required autoFocus value={split.at_time}
              offset={split.at_day_offset} onOffsetChange={(v) => setSplit({ ...split, at_day_offset: v })}
              onChange={(v) => setSplit({ ...split, at_time: v })} />
            <Combobox label="Who finished the duty" options={crewFor(split.crew_role)}
              value={split.employee_id} onChange={(v) => setSplit({ ...split, employee_id: v })}
              placeholder="Nobody - the duty stopped there" />
            <Select label="Why did the driver stop" value={split.reason_id || ""} placeholder="None"
              onChange={(v) => setSplit({ ...split, reason_id: v ? Number(v) : null })}
              options={(reasons || []).filter((r) => r.is_active)
                .map((r) => ({ value: r.reason_id, label: r.reason_name }))} />
            <TextArea label="Remarks" value={split.handover_reason}
              onChange={(e) => setSplit({ ...split, handover_reason: e.target.value })} />
            <p className="text-xs text-slate-500">
              A handover needs a reason code or a remark. Leave the person empty if nobody took the
              duty on - the rest of it is then recorded as not operated.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!reopen} title={`Reopen ${fmtDate(on)}`} onClose={() => setReopen(null)} onSave={runReopen}>
        {reopen && (
          <div className="space-y-3">
            <TextArea label="Why is this day being reopened?" value={reopen.reason}
              onChange={(e) => setReopen({ reason: e.target.value })} />
            <p className="text-xs text-slate-500">
              The reason goes in the audit log. Reopening {fmtDate(on)} also unlocks every day after
              it, because the lock is a single watermark - days before it stay closed.
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}
