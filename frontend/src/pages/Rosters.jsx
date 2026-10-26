import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CalendarRange, CheckCircle2, ChevronDown, Copy, FilePlus2, GitCompare, Lock, Plus, Repeat, Repeat2, Send, Trash2, Undo2, X } from "lucide-react";
import { Link } from "react-router-dom";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Modal, PageHeader, Spinner } from "../components/ui";
import { Checkbox, DateInput, NumberInput, Select, TextArea, TextInput } from "../components/inputs";
import { addDays, fmtDate, label, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

const blankRoster = () => ({
  roster_code: "", roster_name: "",
  period_from: todayIso().slice(0, 8) + "01",
  period_to: addDays(todayIso().slice(0, 8) + "01", 29),
});

const ck = (row, date) => `${row.schedule_id}|${row.shift_number ?? ""}|${row.crew_role}|${date}`;
const EXTRAS = [
  { type: "SPARE", title: "Spare", hint: "Standby crew, not on a bus unless called in" },
  { type: "SHUNTING", title: "Shunting", hint: "Moving buses about the depot" },
];

/**
 * The duty roster grid: duty slots down the left, dates across the top.
 *
 * Rows come from the schedule version in force on each date, not from the roster, so a revised
 * schedule shows its new slots straight away. Spares and shunting drivers have no bus, so they
 * hang off the date instead and any number can be added per day.
 */
export default function Rosters() {
  const { can } = useAuth();
  const toast = useToast();
  const { data: rosters = [], reload: reloadRosters } = useApi("/rosters", []);
  const [rosterId, setRosterId] = useState(null);
  const [grid, setGrid] = useState(null);
  const [loading, setLoading] = useState(false);
  const [issues, setIssues] = useState(null);
  const [newRoster, setNewRoster] = useState(null);
  const [copy, setCopy] = useState(null);
  const [repeat, setRepeat] = useState(null);
  const [publish, setPublish] = useState(null);
  const [revise, setRevise] = useState(null);
  const [generate, setGenerate] = useState(null);
  const [diff, setDiff] = useState(null);
  const [showActuals, setShowActuals] = useState(false);
  const { data: patterns = [] } = useApi("/duty-patterns", []);
  const { data: crewData } = useApi(rosterId ? `/rosters/${rosterId}/crew-options` : null, null);

  const roster = useMemo(() => (rosters || []).find((r) => r.roster_id === rosterId), [rosters, rosterId]);
  const versionCount = (roster?.versions || []).length;
  const editable = can("SCHEDULER") && grid?.status === "DRAFT" && !showActuals;

  useEffect(() => {
    if (!rosterId && (rosters || []).length) setRosterId(rosters[0].roster_id);
  }, [rosters, rosterId]);

  const loadGrid = useCallback(async () => {
    if (!rosterId) return;
    setLoading(true);
    try {
      const r = await client.get(`/rosters/${rosterId}/grid${showActuals ? "?actuals=true" : ""}`);
      setGrid(r.data);
      setIssues(null);
    } catch (e) {
      toast.error(apiErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [rosterId, showActuals]);           // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadGrid(); }, [loadGrid]);

  /** The depot's crew, split by what they can be rostered as. */
  const crewByRole = useMemo(() => {
    const out = { DRIVER: [], CONDUCTOR: [] };
    for (const e of crewData?.crew || []) {
      if (e.status === "ACTIVE" && out[e.staff_type]) out[e.staff_type].push(e);
    }
    return out;
  }, [crewData]);

  const apply = (data) => { setGrid(data); setIssues(null); };
  const fail = (e) => { toast.error(apiErrorMessage(e)); loadGrid(); };

  const saveCell = async (row, date, employeeId) => {
    try {
      const r = await client.put(`/rosters/${rosterId}/assignments`, {
        cells: [{ duty_date: date, schedule_id: row.schedule_id, shift_number: row.shift_number,
                  crew_role: row.crew_role, employee_id: employeeId }],
      });
      apply(r.data);
    } catch (e) { fail(e); }
  };

  const addExtra = async (date, duty_type) => {
    try {
      apply((await client.post(`/rosters/${rosterId}/extras`, { duty_date: date, duty_type })).data);
    } catch (e) { fail(e); }
  };
  const saveExtra = async (extra, employeeId) => {
    try {
      apply((await client.put(`/rosters/${rosterId}/extras/${extra.extra_id}`,
        { employee_id: employeeId, start_time: extra.start_time, end_time: extra.end_time,
          remarks: extra.remarks })).data);
    } catch (e) { fail(e); }
  };
  const removeExtra = async (extra) => {
    try {
      apply((await client.delete(`/rosters/${rosterId}/extras/${extra.extra_id}`)).data);
    } catch (e) { fail(e); }
  };

  const validate = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/validate`);
      setIssues(r.data);
      if (r.data.can_publish) toast.ok(`No errors${r.data.warnings ? ` - ${r.data.warnings} warning(s)` : ""}`);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const createRoster = async () => {
    try {
      const r = await client.post("/rosters", { ...newRoster, roster_name: newRoster.roster_name || null });
      toast.ok(`Roster ${r.data.roster_code} created`);
      setNewRoster(null);
      await reloadRosters();
      setRosterId(r.data.roster_id);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const runCopy = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/copy-days`, copy);
      toast.ok(`${r.data.copied} duties copied${r.data.skipped_days ? `, ${r.data.skipped_days} day(s) skipped` : ""}`);
      apply(r.data);
      setCopy(null);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const runRepeat = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/repeat-block`, repeat);
      toast.ok(`${r.data.copied} duties filled across ${r.data.blocks} block(s)`);
      apply(r.data);
      setRepeat(null);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const runPublish = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/publish`, publish);
      toast.ok(`Version ${r.data.version_number} published${r.data.superseded ? `, version ${r.data.superseded} superseded` : ""}`);
      setPublish(null);
      await reloadRosters();
      loadGrid();
    } catch (e) {
      const msg = apiErrorMessage(e);
      toast.error(msg);
      if (msg.includes("warning")) setPublish({ ...publish, acknowledge_warnings: true });
      if (msg.includes("error")) validate();
    }
  };

  const runRevise = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/versions`, revise);
      toast.ok(`Version ${r.data.version_number} started as a draft`);
      setRevise(null);
      await reloadRosters();
      apply(r.data);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const runUnpublish = async () => {
    if (!window.confirm("Take the published version back to draft?")) return;
    try {
      await client.post(`/rosters/${rosterId}/unpublish`);
      toast.ok("Back to draft");
      await reloadRosters();
      loadGrid();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const runGenerate = async () => {
    try {
      const r = await client.post(`/rosters/${rosterId}/generate`, generate);
      toast.ok(`${r.data.written} duties generated, ${r.data.off_days} off days`
        + (r.data.kept_manual ? `, ${r.data.kept_manual} hand-entered cells kept` : ""));
      apply(r.data);
      setGenerate(null);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const openDiff = async () => {
    try {
      setDiff((await client.get(`/rosters/${rosterId}/diff`)).data);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const notNeeded = useMemo(() => {
    const set = new Set();
    for (const [date, keys] of Object.entries(grid?.not_needed || {})) {
      for (const [sch, shift, role] of keys) set.add(`${sch}|${shift ?? ""}|${role}|${date}`);
    }
    return set;
  }, [grid]);

  const cellIssues = useMemo(() => {
    const out = {};
    for (const i of issues?.issues || []) {
      if (!i.duty_date || !i.schedule_code || !i.slot) continue;
      const row = (grid?.rows || []).find((r) => r.schedule_code === i.schedule_code && r.slot_label === i.slot);
      if (!row) continue;
      const key = ck(row, i.duty_date);
      if (!out[key] || i.severity === "ERROR") out[key] = i;
    }
    return out;
  }, [issues, grid]);

  /** How many rows each extra type needs: the busiest day decides. */
  const extraRows = useMemo(() => {
    const out = {};
    for (const { type } of EXTRAS) {
      let most = 0;
      for (const day of Object.values(grid?.extras || {})) most = Math.max(most, (day[type] || []).length);
      out[type] = most;
    }
    return out;
  }, [grid]);

  const rowCount = (grid?.rows || []).length;

  return (
    <>
      <PageHeader title="Duty roster"
        subtitle="Who is planned to work which bus on which date - buses down, dates across"
        actions={
          <div className="flex items-center gap-2">
            {grid && <Button variant="secondary" icon={CheckCircle2} onClick={validate}>Validate</Button>}
            {editable && <Button variant="secondary" icon={Repeat}
              onClick={() => setRepeat({ source_from: grid.period_from, day_count: 7 })}>Repeat week</Button>}
            {editable && <Button variant="secondary" icon={Copy}
              onClick={() => setCopy({ source_from: grid.period_from, target_from: addDays(grid.period_from, 7), day_count: 7 })}>
              Copy days</Button>}
            {editable && (patterns || []).length > 0 && <Button variant="secondary" icon={Repeat2}
              onClick={() => setGenerate({ pattern_id: patterns[0].pattern_id, overwrite: false })}>Generate</Button>}
            {versionCount > 1 && <Button variant="secondary" icon={GitCompare}
              onClick={openDiff}>Compare versions</Button>}
            {editable && can("PUBLISHER") && <Button icon={Send}
              onClick={() => setPublish({ change_reason: "", acknowledge_warnings: false })}>Publish</Button>}
            {grid?.status === "PUBLISHED" && can("SCHEDULER") && <Button variant="secondary" icon={FilePlus2}
              onClick={() => setRevise({ change_reason: "" })}>Revise</Button>}
            {grid?.status === "PUBLISHED" && can("PUBLISHER") && <Button variant="secondary" icon={Undo2}
              onClick={runUnpublish}>Unpublish</Button>}
            {can("SCHEDULER") && <Button icon={Plus} onClick={() => setNewRoster(blankRoster())}>New roster</Button>}
          </div>
        } />

      <Card className="mb-3">
        <div className="flex flex-wrap items-end gap-3">
          <Select label="Roster" className="w-72" value={rosterId || ""} onChange={(v) => setRosterId(Number(v))}
            options={(rosters || []).map((r) => ({
              value: r.roster_id,
              label: `${r.roster_code}${r.roster_name ? ` - ${r.roster_name}` : ""} (${fmtDate(r.period_from)} to ${fmtDate(r.period_to)})`,
            }))} placeholder="No rosters yet" />
          <div className="flex rounded-md border border-slate-300">
            {[[false, "Plan"], [true, "Plan vs actual"]].map(([v, title]) => (
              <button key={title} type="button" onClick={() => setShowActuals(v)}
                className={`px-3 py-2 text-xs font-medium first:rounded-l-md last:rounded-r-md ${
                  showActuals === v ? "bg-slate-800 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
                {title}
              </button>
            ))}
          </div>
          {grid && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <Badge value={grid.status} />
              <span>Version {grid.version_number}</span>
              <span>·</span><span>{rowCount} bus duty slots</span>
              <span>·</span><span>{grid.days.length} days</span>
              <span>·</span><span>{(crewData?.crew || []).length} crew in this depot</span>
              {grid.locked_through && (
                <span className="inline-flex items-center gap-1 text-slate-500">
                  <Lock className="h-3 w-3" /> locked through {fmtDate(grid.locked_through)}
                </span>
              )}
            </div>
          )}
        </div>
      </Card>

      {issues && (
        <Card className="mb-3" title={issues.can_publish
          ? `Ready to publish${issues.warnings ? ` - ${issues.warnings} warning(s)` : ""}`
          : `${issues.errors} error(s), ${issues.warnings} warning(s)`}>
          {issues.issues.length === 0
            ? <p className="text-sm text-slate-500">Every slot is filled and every rule holds.</p>
            : <ul className="max-h-48 space-y-1 overflow-auto text-xs">
              {issues.issues.slice(0, 200).map((i, n) => (
                <li key={n} className="flex items-start gap-2">
                  <span className={i.severity === "ERROR" ? "font-semibold text-rose-700" : "font-semibold text-amber-700"}>
                    {i.severity === "ERROR" ? "Error" : "Warning"}
                  </span>
                  <span className="text-slate-600">
                    {i.duty_date && <span className="mr-1 font-mono">{fmtDate(i.duty_date)}</span>}
                    {i.message}
                  </span>
                </li>
              ))}
            </ul>}
        </Card>
      )}

      {showActuals && grid && (
        <Card className="mb-3">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-slate-600">
            <span className="font-semibold text-ink">Planned above, who actually worked below</span>
            {[["bg-white border-slate-300", "As planned"], ["bg-brand-50 border-brand-200", "Replaced"],
              ["bg-amber-50 border-amber-200", "Handed over part-way"],
              ["bg-rose-50 border-rose-200", "Nobody worked it"],
              ["bg-slate-100 border-slate-300", "Not operated"],
              ["bg-slate-50 border-dashed border-slate-300", "Not recorded yet"]].map(([cls, title]) => (
              <span key={title} className="inline-flex items-center gap-1.5">
                <span className={`inline-block h-3 w-3 rounded border ${cls}`} />{title}
              </span>
            ))}
            <span className="text-slate-500">
              {grid.recorded_days?.length || 0} of {grid.days.length} days recorded ·
              {" "}<Link className="text-brand-600 hover:underline" to="/duty-day">record a day</Link>
            </span>
          </div>
        </Card>
      )}

      {loading && <div className="py-10 text-center"><Spinner /></div>}

      {!loading && grid && (
        <div className="overflow-auto rounded-lg border border-slate-200 bg-white">
          <table className="table-fixed border-separate border-spacing-0 text-sm" style={{ width: "max-content" }}>
            {/* fixed widths: the sticky left offsets below are these same numbers, so the
                two frozen columns meet exactly instead of leaving a gap */}
            <colgroup>
              <col style={{ width: 160 }} />
              <col style={{ width: 144 }} />
              {grid.days.map((d) => <col key={d.duty_date} style={{ width: 112 }} />)}
            </colgroup>
            <thead>
              <tr>
                <th className="sticky left-0 top-0 z-30 w-40 border-b border-r border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-semibold text-slate-600">
                  Bus / schedule
                </th>
                <th className="sticky left-[160px] top-0 z-30 w-36 border-b border-r border-slate-300 bg-slate-50 px-3 py-2 text-left text-xs font-semibold text-slate-600">
                  Duty slot
                </th>
                {grid.days.map((d) => (
                  <th key={d.duty_date} className="sticky top-0 z-20 w-28 border-b border-r border-slate-200 bg-slate-50 px-1 py-2 text-center">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">{d.weekday}</div>
                    <div className="text-xs font-semibold text-ink">{d.duty_date.slice(8)}</div>
                    {d.locked && <div className="text-[9px] text-slate-400">closed</div>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.rows.map((row, ri) => (
                <tr key={ck(row, "row")}>
                  <th scope="row" className="sticky left-0 z-10 border-b border-r border-slate-200 bg-white px-3 py-1.5 text-left align-top">
                    <div className="text-[13px] font-semibold text-ink">{row.fleet_number}</div>
                    <div className="text-[11px] text-slate-500">{row.schedule_code}</div>
                  </th>
                  <td className="sticky left-[160px] z-10 border-b border-r border-slate-300 bg-white px-3 py-1.5 align-top">
                    <div className="text-xs text-ink">{label(row.crew_role)}{row.shift_name ? ` · ${row.shift_name}` : ""}</div>
                    {row.duty_from && <div className="text-[11px] text-slate-500">{row.duty_from}–{row.duty_to}</div>}
                  </td>
                  {grid.days.map((d, di) => {
                    const cell = row.cells[d.duty_date];
                    const key = ck(row, d.duty_date);
                    if (!cell || notNeeded.has(key)) {
                      return <td key={key} title={`${row.schedule_code} does not run on ${fmtDate(d.duty_date)}`}
                        className="border-b border-r border-slate-200 bg-slate-100 px-1 py-1.5 text-center text-xs text-slate-400">—</td>;
                    }
                    if (showActuals) {
                      return <ActualCell key={key} cell={cell} />;
                    }
                    return (
                      <td key={key} className={`border-b border-r border-slate-200 p-0 align-top ${
                        cellIssues[key]?.severity === "ERROR" ? "bg-rose-50" : cellIssues[key] ? "bg-amber-50" : ""}`}>
                        <CrewPicker crew={crewByRole[row.crew_role] || []} value={cell.employee_id}
                          display={cell.employee_number} name={cell.employee_name}
                          disabled={cell.locked || !editable} coord={`${ri}-${di}`}
                          title={cellIssues[key]?.message}
                          onPick={(id) => saveCell(row, d.duty_date, id)} />
                      </td>
                    );
                  })}
                </tr>
              ))}

              {EXTRAS.map(({ type, title, hint }) => (
                <ExtraBlock key={type} type={type} title={title} hint={hint} grid={grid}
                  slots={extraRows[type]} editable={editable} crew={crewByRole} showActuals={showActuals}
                  baseRow={rowCount} onAdd={addExtra} onPick={saveExtra} onRemove={removeExtra} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !grid && (
        <Card>
          <p className="inline-flex items-center gap-2 text-sm text-slate-500">
            <CalendarRange className="h-4 w-4" /> No roster yet. Create one for a period and the grid appears.
          </p>
        </Card>
      )}

      <p className="mt-2 text-xs text-slate-500">
        Pick a driver from the cell's dropdown, or type a number or name to filter it. <b>Enter</b> saves and
        moves down, <b>Tab</b> moves across the day, arrows walk the list, <b>Esc</b> closes it, and
        <b> Delete</b> clears a cell. A grey dash means that bus does not run that day - the schedule's
        effective dates decide. A draft can be edited on every date, past days included, until it is published.
      </p>

      <Modal open={!!newRoster} title="New roster period" onClose={() => setNewRoster(null)} onSave={createRoster}>
        {newRoster && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Code" required autoFocus value={newRoster.roster_code}
              onChange={(e) => setNewRoster({ ...newRoster, roster_code: e.target.value.toUpperCase().replace(/\s+/g, "-") })} />
            <TextInput label="Name" value={newRoster.roster_name}
              onChange={(e) => setNewRoster({ ...newRoster, roster_name: e.target.value })} />
            <DateInput label="First day" required value={newRoster.period_from}
              onChange={(v) => setNewRoster({ ...newRoster, period_from: v })} />
            <DateInput label="Last day" required value={newRoster.period_to} base={newRoster.period_from}
              onChange={(v) => setNewRoster({ ...newRoster, period_to: v })} />
            <p className="col-span-2 text-xs text-slate-500">
              Periods cannot overlap another roster. Type the first week, then use <b>Repeat week</b> to fill
              the rest of the period from it.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!repeat} title="Repeat a week across the period" onClose={() => setRepeat(null)} onSave={runRepeat}>
        {repeat && (
          <div className="grid grid-cols-2 gap-3">
            <DateInput label="Repeat the block starting" required autoFocus value={repeat.source_from}
              onChange={(v) => setRepeat({ ...repeat, source_from: v })} />
            <NumberInput label="Days in the block" integer min={1} max={31} value={repeat.day_count}
              onChange={(v) => setRepeat({ ...repeat, day_count: v })} />
            <p className="col-span-2 text-xs text-slate-500">
              The block is copied forward again and again to the end of the period, so a typed week becomes the
              whole month. The last block stops at the period's last day. Slots a date does not need are
              skipped, and closed days are left alone. Cells already filled are overwritten.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!publish} title="Publish the roster" onClose={() => setPublish(null)} onSave={runPublish}>
        {publish && (
          <div className="space-y-3">
            <TextArea label="What changed, and why" value={publish.change_reason}
              onChange={(e) => setPublish({ ...publish, change_reason: e.target.value })} />
            <Checkbox label="I have seen the warnings and want to publish anyway"
              checked={publish.acknowledge_warnings}
              onChange={(v) => setPublish({ ...publish, acknowledge_warnings: v })} />
            <p className="text-xs text-slate-500">
              Publishing freezes this version: its duties cannot be changed again. To alter anything
              afterwards you start a revision, which copies the whole period into a new version -
              days already closed come across untouched.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!revise} title="Start a revision" onClose={() => setRevise(null)} onSave={runRevise}>
        {revise && (
          <div className="space-y-3">
            <TextArea label="Why is the roster being revised?" value={revise.change_reason}
              onChange={(e) => setRevise({ change_reason: e.target.value })} />
            <p className="text-xs text-slate-500">
              The whole period is copied into a new draft, completed days included - those stay locked,
              so only days still to come can differ. The published version keeps running until the new
              one is published.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!generate} title="Generate from a duty pattern" onClose={() => setGenerate(null)}
        onSave={runGenerate}>
        {generate && (
          <div className="space-y-3">
            <Select label="Pattern" required value={generate.pattern_id}
              onChange={(v) => setGenerate({ ...generate, pattern_id: Number(v) })}
              options={(patterns || []).map((p) => ({ value: p.pattern_id,
                label: `${p.pattern_code} - ${p.cycle_days} day cycle, ${p.members.length} crew` }))} />
            <DateInput label="Day 1 of the cycle falls on" value={generate.anchor || grid?.period_from}
              onChange={(v) => setGenerate({ ...generate, anchor: v })} />
            <Checkbox label="Overwrite cells entered by hand as well" checked={generate.overwrite}
              onChange={(v) => setGenerate({ ...generate, overwrite: v })} />
            <p className="text-xs text-slate-500">
              The rotation is written across the period. Days a bus does not run, and days already
              closed, are skipped. Hand-entered cells are kept unless you tick the box above.
            </p>
          </div>
        )}
      </Modal>

      <Modal open={!!diff} wide title={diff ? `Version ${diff.base.version_number} → ${diff.other.version_number}` : ""}
        onClose={() => setDiff(null)} footer={<Button onClick={() => setDiff(null)}>Close</Button>}>
        {diff && (
          <div className="space-y-3 text-sm">
            <p className="text-xs text-slate-500">
              {diff.changes} change(s)
              {diff.carried_over ? `, ${diff.carried_over} duty on closed days carried over unchanged` : ""}
              {diff.locked_through ? ` (closed through ${fmtDate(diff.locked_through)})` : ""}
            </p>
            {diff.changes === 0 && <p className="text-slate-500">The two versions are identical.</p>}
            {[["Bus duties", diff.rows], ["Spares and shunting", diff.extras]].map(([title, rows]) => rows.length > 0 && (
              <div key={title}>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-slate-500">
                    <th className="py-1">Day</th><th>Duty</th><th>Was</th><th>Now</th><th>Change</th>
                  </tr></thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td className="py-1 font-mono">{fmtDate(r.duty_date)}</td>
                        <td>{r.schedule_code || label(r.duty_type)}{r.shift_number ? ` · shift ${r.shift_number}` : ""}
                          {r.slot_index ? ` ${r.slot_index}` : ""} <span className="text-slate-400">{label(r.crew_role)}</span></td>
                        <td className="text-slate-500">{r.before?.employee_name || "—"}</td>
                        <td className="font-medium">{r.after?.employee_name || "—"}</td>
                        <td>{r.locked ? <span className="text-slate-400">locked</span> : label(r.change)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal open={!!copy} title="Copy days" onClose={() => setCopy(null)} onSave={runCopy}>
        {copy && (
          <div className="grid grid-cols-2 gap-3">
            <DateInput label="Copy from" required autoFocus value={copy.source_from}
              onChange={(v) => setCopy({ ...copy, source_from: v })} />
            <DateInput label="Copy onto" required value={copy.target_from} base={copy.source_from}
              onChange={(v) => setCopy({ ...copy, target_from: v })} />
            <NumberInput label="How many days" integer min={1} max={31} value={copy.day_count}
              onChange={(v) => setCopy({ ...copy, day_count: v })} />
            <p className="col-span-2 text-xs text-slate-500">
              One stretch of days onto another. For filling a whole period from one week, use
              <b> Repeat week</b> instead.
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}

/**
 * One cell of the plan-vs-actual view: what was planned above, who actually worked below.
 *
 * A duty handed over part-way shows both names with the time of the change, because that is the
 * thing a depot wants to see at a glance.
 */
function ActualCell({ cell }) {
  const tone = {
    REPLACED: "bg-brand-50", HANDED_OVER: "bg-amber-50", ABSENT: "bg-rose-50",
    NOT_OPERATED: "bg-slate-100", AS_PLANNED: "",
  }[cell.actual_status] ?? (cell.employee_id ? "bg-slate-50/60" : "");

  const planned = cell.employee_name;
  const changed = cell.recorded && cell.actual_status !== "AS_PLANNED";
  const title = [
    planned ? `Planned: ${planned}` : "Nobody planned",
    ...(cell.actual || []).map((a) => `${a.employee_name || "nobody"}`
      + (a.from_time ? ` ${a.from_time}–${a.to_time}` : "")
      + (a.reason ? ` (${a.reason})` : "")),
    !cell.recorded ? "Not recorded yet" : null,
  ].filter(Boolean).join("\n");

  return (
    <td className={`border-b border-r border-slate-200 px-2 py-1.5 align-top ${tone}`} title={title}>
      {planned ? (
        <div className={`truncate text-[11px] leading-tight ${
          changed ? "text-slate-400 line-through" : "text-ink"}`}>{planned}</div>
      ) : (
        <div className="text-[11px] leading-tight text-slate-300">—</div>
      )}

      {!cell.recorded && planned && (
        <div className="text-[10px] leading-tight text-slate-400">not recorded</div>
      )}

      {(cell.actual || []).map((a, i) => (
        <div key={i} className="truncate text-[11px] font-medium leading-tight text-brand-800">
          {a.employee_name || <span className="text-rose-700">nobody</span>}
          {cell.actual.length > 1 && a.from_time && (
            <span className="ml-1 font-normal text-slate-500">{a.from_time}</span>
          )}
        </div>
      ))}

      {cell.actual_status === "NOT_OPERATED" && (
        <div className="text-[10px] leading-tight text-slate-500">not operated</div>
      )}
    </td>
  );
}


/** Spares or shunting: no bus, so one row per slot number plus a row of add buttons. */
function ExtraBlock({ type, title, hint, grid, slots, editable, crew, showActuals, baseRow, onAdd, onPick, onRemove }) {
  const rows = [];
  for (let i = 0; i < slots; i++) {
    rows.push(
      <tr key={`${type}-${i}`}>
        {i === 0 && (
          <th scope="row" rowSpan={slots} className="sticky left-0 z-10 border-b border-r border-slate-200 bg-slate-50 px-3 py-1.5 text-left align-top">
            <div className="text-[13px] font-semibold text-ink">{title}</div>
            <div className="text-[11px] text-slate-500">{hint}</div>
          </th>
        )}
        <td className="sticky left-[160px] z-10 border-b border-r border-slate-300 bg-slate-50 px-3 py-1.5 align-top">
          <div className="text-xs text-ink">{title} {i + 1}</div>
        </td>
        {grid.days.map((d, di) => {
          const list = grid.extras[d.duty_date]?.[type] || [];
          const extra = list[i];
          if (!extra) {
            return <td key={d.duty_date} className="border-b border-r border-slate-200 bg-slate-50/60 px-1 text-center text-xs text-slate-300">·</td>;
          }
          if (showActuals) {
            return <ActualCell key={d.duty_date} cell={{ ...extra, employee_name: extra.employee_name }} />;
          }
          return (
            <td key={d.duty_date} className="border-b border-r border-slate-200 p-0 align-top">
              <div className="flex items-start">
                <CrewPicker crew={crew[extra.crew_role] || []} value={extra.employee_id}
                  display={extra.employee_number} name={extra.employee_name}
                  disabled={!editable} coord={`${baseRow + i}-${di}`}
                  onPick={(id) => onPick(extra, id)} />
                {editable && (
                  <button type="button" tabIndex={-1} title="Remove this duty"
                    className="mt-1 mr-1 text-slate-300 hover:text-rose-600"
                    onClick={() => onRemove(extra)}><X className="h-3 w-3" /></button>
                )}
              </div>
            </td>
          );
        })}
      </tr>
    );
  }
  if (editable) {
    rows.push(
      <tr key={`${type}-add`}>
        {slots === 0 && (
          <th scope="row" className="sticky left-0 z-10 border-b border-r border-slate-200 bg-slate-50 px-3 py-1.5 text-left align-top">
            <div className="text-[13px] font-semibold text-ink">{title}</div>
            <div className="text-[11px] text-slate-500">{hint}</div>
          </th>
        )}
        {slots > 0 && <th scope="row" className="sticky left-0 z-10 border-b border-r border-slate-200 bg-slate-50" />}
        <td className="sticky left-[160px] z-10 border-b border-r border-slate-300 bg-slate-50 px-3 py-1 align-top">
          <div className="text-[11px] text-slate-500">add per day</div>
        </td>
        {grid.days.map((d) => (
          <td key={d.duty_date} className="border-b border-r border-slate-200 bg-slate-50/60 p-0 text-center">
            <button type="button" tabIndex={-1} disabled={d.locked}
              title={`Add a ${title.toLowerCase()} duty on ${fmtDate(d.duty_date)}`}
              className="w-full py-1 text-slate-400 hover:bg-brand-50 hover:text-brand-700 disabled:text-slate-200"
              onClick={() => onAdd(d.duty_date, type)}><Plus className="mx-auto h-3.5 w-3.5" /></button>
          </td>
        ))}
      </tr>
    );
  }
  return rows;
}

/**
 * A cell that picks crew from the depot's list. Shows the employee number, opens a dropdown on
 * focus, and filters it as you type - so it works by mouse and by keyboard alone.
 */
function CrewPicker({ crew, value, display, name, disabled, coord, title, onPick }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hi, setHi] = useState(0);
  const listRef = useRef(null);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return crew;
    return crew.filter((e) => e.employee_number.toLowerCase().includes(q)
      || e.employee_name.toLowerCase().includes(q));
  }, [crew, query]);

  useEffect(() => setHi(0), [query]);
  useEffect(() => { listRef.current?.children[hi]?.scrollIntoView({ block: "nearest" }); }, [hi, open]);

  const move = (dr, dc) => {
    const [r, c] = coord.split("-").map(Number);
    document.querySelector(`[data-cell="${r + dr}-${c + dc}"]`)?.focus();
  };
  const close = () => { setOpen(false); setQuery(""); };
  const choose = (e, then) => {
    close();
    if ((e?.employee_id ?? null) !== (value ?? null)) onPick(e ? e.employee_id : null);
    then?.();
  };

  const keyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setHi((h) => Math.min(h + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) move(-1, 0); else setHi((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && matches[hi]) choose(matches[hi], () => move(1, 0));
      else move(1, 0);
    } else if (e.key === "Tab") {
      if (open && matches[hi] && query) { e.preventDefault(); choose(matches[hi], () => move(0, 1)); }
      else close();
    } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Delete" || (e.key === "Backspace" && !query)) { e.preventDefault(); choose(null); }
    else if (e.key === "ArrowRight" && !open) { e.preventDefault(); move(0, 1); }
    else if (e.key === "ArrowLeft" && !open) { e.preventDefault(); move(0, -1); }
  };

  return (
    <div className="relative">
      <input data-cell={coord} disabled={disabled} role="combobox" aria-expanded={open} autoComplete="off"
        aria-label={name || "unassigned"} title={title || name || undefined}
        className="h-11 w-28 border-0 bg-transparent px-2 text-xs text-ink placeholder-slate-300 focus:bg-brand-50 focus:outline-none focus:ring-1 focus:ring-brand-400 disabled:text-slate-400"
        value={open ? query : display || ""} placeholder={disabled ? "" : "—"}
        onFocus={(e) => { e.target.select(); setOpen(true); }}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onBlur={() => setTimeout(close, 120)}
        onKeyDown={keyDown} />
      {!open && name && <div className="truncate px-2 pb-1 text-[10px] text-slate-500">{name}</div>}
      {!open && !disabled && (
        <ChevronDown className="pointer-events-none absolute right-1 top-3.5 h-3 w-3 text-slate-300" />
      )}
      {open && (
        <ul ref={listRef} className="absolute z-50 mt-0.5 max-h-56 w-56 overflow-auto rounded-md border border-slate-200 bg-white py-1 text-xs shadow-lg">
          {matches.length === 0 && <li className="px-3 py-2 text-slate-400">Nobody matches</li>}
          {matches.map((e, i) => (
            <li key={e.employee_id} onMouseDown={(ev) => { ev.preventDefault(); choose(e); }}
              onMouseEnter={() => setHi(i)}
              className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 ${
                i === hi ? "bg-brand-50 text-brand-800" : "text-ink"}`}>
              <span className="truncate">{e.employee_name}</span>
              <span className="font-mono text-[10px] text-slate-400">{e.employee_number}</span>
            </li>
          ))}
          {value && (
            <li onMouseDown={(ev) => { ev.preventDefault(); choose(null); }}
              className="mt-1 flex cursor-pointer items-center gap-2 border-t border-slate-100 px-3 py-1.5 text-slate-500 hover:bg-slate-50">
              <Trash2 className="h-3 w-3" /> Clear this cell
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
