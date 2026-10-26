import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CornerDownRight, FileScan, Plus, Repeat, RotateCcw, Save, Send, ShieldCheck, Trash2, UserPlus, UserX, Wand2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Spinner } from "../components/ui";
import ScanImage from "../components/ScanImage";
import { Checkbox, Combobox, NumberInput, Select, TextArea, TextInput, TimeInput } from "../components/inputs";
import { Tile } from "../components/viz/SummaryTiles";
import { TYPE_COLOR } from "../components/viz/colors";
import { fmtDate, fmtDateLong, fmtDuration, fmtRel, label, num, options, relMin } from "../lib/format";
import { gridArrows } from "../lib/grid";
import { useFormKeys } from "../lib/keys";
import { locOptions, useApi } from "../lib/useApi";

const STATUSES = ["PENDING", "OPERATED", "PARTIAL", "CANCELLED"];
// row groups for the show/hide chips (payable movements toggle apart from the other movements)
const GROUPS = [["PASSENGER_TRIP", "Trips"], ["NON_REVENUE_MOVEMENT", "Movement"], ["PAYABLE", "Payable movement"],
  ["CHARGING", "Charging"], ["LAYOVER", "Layover"], ["HALT", "Halt"], ["EXTRA", "Extra runs"]];
const groupOf = (r) => (!r.planned ? "EXTRA" : r.planned.payability_status === "PAYABLE" ? "PAYABLE" : r.planned.activity_type);
// v2: earlier saved choices predate the charging/layover-off default, so start everyone fresh once
const FILTER_KEY = "depot_tripsheet_hidden_v2";
// charging and layovers are mostly filled by "Fill in layovers & SOC", so they start hidden
const DEFAULT_HIDDEN = ["CHARGING", "LAYOVER"];
function storedFilter() {
  try {
    const raw = localStorage.getItem(FILTER_KEY);
    if (raw === null) return { hidden: new Set(DEFAULT_HIDDEN), pendingOnly: false };
    const v = JSON.parse(raw);
    return { hidden: new Set(v.hidden || []), pendingOnly: !!v.pendingOnly };
  } catch { return { hidden: new Set(DEFAULT_HIDDEN), pendingOnly: false }; }
}
const ATTR = ["OPERATOR", "CLIENT", "EXTERNAL"];

/** Editable copy of a row from the API (numbers as numbers, stops keyed for the stop grid). */
function toEdit(r) {
  const saved = Object.fromEntries((r.stops || []).map((s) => [s.scheduled_stop_time_id, s]));
  return {
    row_id: r.row_id, status: r.status,
    actual_start_day_offset: r.actual_start_day_offset ?? 0, actual_start_time: r.actual_start_time,
    actual_end_day_offset: r.actual_end_day_offset ?? 0, actual_end_time: r.actual_end_time,
    start_odometer_km: num(r.start_odometer_km), end_odometer_km: num(r.end_odometer_km),
    start_soc_pct: num(r.start_soc_pct), end_soc_pct: num(r.end_soc_pct), energy_kwh: num(r.energy_kwh),
    stopped_at_route_stop_id: r.stopped_at_route_stop_id, reason_id: r.reason_id, attributable_to: r.attributable_to,
    remarks: r.remarks || "", extra_from_location_id: r.extra_from_location_id, extra_to_location_id: r.extra_to_location_id,
    extra_payable: r.extra_payable,
    stops: (r.planned?.stops || []).map((p) => {
      const s = saved[p.scheduled_stop_time_id] || {};
      return { scheduled_stop_time_id: p.scheduled_stop_time_id, arrival_day_offset: s.arrival_day_offset ?? p.arrival_day_offset ?? 0,
        arrival_time: s.arrival_time || null, departure_day_offset: s.departure_day_offset ?? p.departure_day_offset ?? 0,
        departure_time: s.departure_time || null, odometer_km: num(s.odometer_km), soc_pct: num(s.soc_pct) };
    }),
  };
}

const crewEdit = (c) => ({
  crew_id: c.crew_id, employee_id: c.employee_id, duty_start_day_offset: c.duty_start_day_offset ?? 0, duty_start_time: c.duty_start_time,
  duty_end_day_offset: c.duty_end_day_offset ?? 0, duty_end_time: c.duty_end_time, handover_reason: c.handover_reason,
});

function IssueList({ result, onPick }) {
  if (!result) return null;
  if (!result.issues.length) return <p className="flex items-center gap-2 text-sm font-medium text-[#0a6e0a]"><CheckCircle2 className="h-4 w-4" /> No errors or warnings - ready to submit</p>;
  const errs = result.issues.filter((i) => i.severity === "ERROR");
  return (
    <div className="space-y-1">
      <p className="text-sm"><b className="text-danger">{errs.length} error{errs.length !== 1 && "s"}</b> · <b className="text-[#8a5a00]">{result.issues.length - errs.length} warning{result.issues.length - errs.length !== 1 && "s"}</b>
        <span className="ml-2 text-xs text-slate-500">Errors block submitting; warnings do not.</span></p>
      <ul className="max-h-56 overflow-auto">
        {[...errs, ...result.issues.filter((i) => i.severity !== "ERROR")].map((i, k) => (
          <li key={k}><button type="button" onClick={() => i.row_id && onPick(i.row_id)} className="flex w-full items-start gap-2 rounded px-2 py-0.5 text-left text-sm hover:bg-slate-50">
            {i.severity === "ERROR" ? <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#b07800]" />}
            <span>{i.message} <span className="text-[11px] text-slate-400">{i.code}</span></span>
          </button></li>
        ))}
      </ul>
    </div>
  );
}

export default function TripSheet() {
  const { sheetId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { canIn, companyOf } = useAuth();
  const { data: sheet, setData: setSheet } = useApi(`/trip-sheets/${sheetId}`);
  const { data: reasons = [] } = useApi("/trip-reasons", []);
  // what the scanned paper could not tell us, if this sheet was filled from a scan
  const { data: scan } = useApi(`/trip-sheets/${sheetId}/scan`);
  const { data: allLocs = [] } = useApi("/locations", []);
  const { data: buses = [] } = useApi("/vehicles", []);
  const { data: staff = [] } = useApi(sheet ? `/employees?available_on=${sheet.operating_date}` : null, []);
  const [rows, setRows] = useState({});
  const [crew, setCrew] = useState({});
  const [head, setHead] = useState({ paper_sheet_no: "", remarks: "", paper_version_number: null,
    bus_change_registration: "", bus_change_from_row_id: null, bus_change_reason_id: null });
  const [dirty, setDirty] = useState(false);
  const [open, setOpen] = useState({});
  const [result, setResult] = useState(null);
  const [paper, setPaper] = useState(null);         // the scanned page being read full size
  const [handover, setHandover] = useState(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState(storedFilter);
  const grid = useRef(null);

  const load = (s) => {
    setSheet(s);
    setRows(Object.fromEntries(s.rows.map((r) => [r.row_id, toEdit(r)])));
    setCrew(Object.fromEntries(s.crew.map((c) => [c.crew_id, crewEdit(c)])));
    setHead({ paper_sheet_no: s.paper_sheet_no || "", remarks: s.remarks || "", paper_version_number: s.paper_version_number,
      bus_change_registration: s.bus_change_registration || "", bus_change_from_row_id: s.bus_change_from_row_id,
      bus_change_reason_id: s.bus_change_reason_id });
    setDirty(false);
  };
  useEffect(() => { if (sheet && !Object.keys(rows).length) load(sheet); }, [sheet]); // eslint-disable-line react-hooks/exhaustive-deps

  const editable = sheet?.status === "DRAFT" && canIn(sheet?.cost_center_id, "MIS");
  const company = sheet ? companyOf(sheet.cost_center_id) : null;
  const myReasons = useMemo(() => (reasons || []).filter((r) => r.is_active && (company === null || r.company_id === company)), [reasons, company]);
  const locs = (allLocs || []).filter((l) => company === null || l.company_id === company);
  const staffOpts = (role) => (staff || []).filter((e) => e.cost_center_id === sheet?.cost_center_id && e.staff_type === role)
    .map((e) => ({ value: e.employee_id, label: e.full_name, sub: e.employee_number }));
  const tol = Number(sheet?.billing_rule?.odometer_tolerance_pct ?? 10);

  const ordered = useMemo(() => (sheet?.rows || []).slice().sort((a, b) => a.row_sequence - b.row_sequence), [sheet]);
  const saveFilter = (f) => { setFilter(f); try { localStorage.setItem(FILTER_KEY, JSON.stringify({ hidden: [...f.hidden], pendingOnly: f.pendingOnly })); } catch { /* private mode */ } };
  const toggleGroup = (g) => { const h = new Set(filter.hidden); if (h.has(g)) h.delete(g); else h.add(g); saveFilter({ ...filter, hidden: h }); };
  // hidden rows stay in the sheet and are still saved; this only narrows what is on screen
  const visible = ordered.filter((r) => !filter.hidden.has(groupOf(r)) && (!filter.pendingOnly || r.status === "PENDING")); // saved status, so a row does not vanish while being typed
  const setRow = (id, patch) => { setRows((x) => ({ ...x, [id]: { ...x[id], ...patch } })); setDirty(true); };
  const setCrewRow = (id, patch) => { setCrew((x) => ({ ...x, [id]: { ...x[id], ...patch } })); setDirty(true); };
  const prevEndOdo = (rowId) => {
    const i = ordered.findIndex((r) => r.row_id === rowId);
    for (let j = i - 1; j >= 0; j--) { const v = rows[ordered[j].row_id]?.end_odometer_km; if (v !== null && v !== undefined) return v; }
    // first run of the day: the bus stood in the depot overnight, so it starts where the last sheet closed
    return sheet?.previous_closing ? num(sheet.previous_closing.odometer_km) : null;
  };
  /** One keystroke for a row that ran to plan: status, planned times and the odometer carried from the row above. */
  const asPlanned = (r) => {
    const p = r.planned;
    const driving = !p || ["PASSENGER_TRIP", "NON_REVENUE_MOVEMENT"].includes(p.activity_type);
    setRow(r.row_id, {
      status: "OPERATED", reason_id: null, attributable_to: null, stopped_at_route_stop_id: null,
      ...(p ? { actual_start_day_offset: p.start_day_offset, actual_start_time: p.start_time, actual_end_day_offset: p.end_day_offset, actual_end_time: p.end_time } : {}),
      ...(driving && rows[r.row_id].start_odometer_km === null ? { start_odometer_km: prevEndOdo(r.row_id) } : {}),
    });
  };

  /** Carry the actuals through the stationary rows: layovers and halts take their times from the runs around
   * them; layovers, charging and halts take SOC from the previous end and the next start. Cancelled rows are
   * skipped; an un-entered neighbour blocks the fill on that side. Nothing is saved until Save. */
  const fillStationary = () => {
    const next = { ...rows };
    const ran = (id) => !["CANCELLED"].includes(next[id].status);
    // the neighbouring run that actually ran (cancelled rows are skipped); if it is not entered yet, nothing is
    // taken from further away - that could overlap the un-entered run
    const near = (idx, step, pick) => {
      for (let j = idx + step; j >= 0 && j < ordered.length; j += step) {
        if (!ran(ordered[j].row_id)) continue;
        const v = pick(next[ordered[j].row_id]);
        return v === undefined ? null : v;
      }
      return null;
    };
    let times = 0, socs = 0;
    ordered.forEach((r, idx) => {
      const type = r.planned?.activity_type;
      if (!["LAYOVER", "CHARGING", "HALT"].includes(type) || next[r.row_id].status === "CANCELLED") return;
      const e = { ...next[r.row_id] };
      const before = JSON.stringify(e);
      if (type !== "CHARGING") {
        const end = near(idx, -1, (x) => (x.actual_end_time ? [x.actual_end_day_offset ?? 0, x.actual_end_time] : null));
        const start = near(idx, 1, (x) => (x.actual_start_time ? [x.actual_start_day_offset ?? 0, x.actual_start_time] : null));
        const s0 = end ?? [e.actual_start_day_offset, e.actual_start_time];
        const e0 = start ?? [e.actual_end_day_offset, e.actual_end_time];
        if (s0[1] && e0[1] && relMin(e0[0], e0[1]) > relMin(s0[0], s0[1])) {
          [e.actual_start_day_offset, e.actual_start_time] = s0;
          [e.actual_end_day_offset, e.actual_end_time] = e0;
          if (e.status === "PENDING") e.status = "OPERATED";
        }
      }
      const ps = near(idx, -1, (x) => x.end_soc_pct), ns = near(idx, 1, (x) => x.start_soc_pct);
      if (ps !== null) e.start_soc_pct = ps;
      if (ns !== null) e.end_soc_pct = ns;
      if (JSON.stringify(e) !== before) {
        next[r.row_id] = e;
        if (e.actual_start_time !== JSON.parse(before).actual_start_time || e.actual_end_time !== JSON.parse(before).actual_end_time) times += 1;
        else socs += 1;
      }
    });
    setRows(next);
    if (times || socs) { setDirty(true); toast.ok(`Filled ${times} layover/halt time${times === 1 ? "" : "s"} and ${socs} SOC-only row${socs === 1 ? "" : "s"} - review, then Save`); }
    else toast.ok("Nothing to fill - enter the runs' actual times and SOC first");
  };

  const payload = () => ({
    paper_sheet_no: head.paper_sheet_no || null, remarks: head.remarks || null,
    paper_version_number: head.paper_version_number || null,
    bus_change_registration: head.bus_change_registration || null,
    bus_change_from_row_id: head.bus_change_registration ? head.bus_change_from_row_id : null,
    bus_change_reason_id: head.bus_change_registration ? head.bus_change_reason_id : null,
    rows: ordered.map((r) => {
      const e = rows[r.row_id];
      return { ...e, remarks: e.remarks || null, stops: r.planned?.stops ? e.stops : null };
    }),
    crew: Object.values(crew),
  });
  const run = async (fn, ok) => {
    setBusy(true);
    try {
      const { data } = await fn();
      if (data?.rows) load(data);
      if (ok) toast.ok(ok);
      return data;
    } catch (e) {
      const issues = e?.response?.data?.detail?.issues;
      if (issues) setResult({ issues });
      toast.error(apiErrorMessage(e));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(() => client.put(`/trip-sheets/${sheetId}`, payload()), "Trip sheet saved");
  const validate = async () => {
    if (dirty && editable && !(await save())) return;
    const r = await run(() => client.post(`/trip-sheets/${sheetId}/validate`));
    if (r) setResult(r);
  };
  const submit = async () => {
    if (dirty && !(await save())) return;
    if (await run(() => client.post(`/trip-sheets/${sheetId}/submit`), "Submitted for approval")) setResult(null);
  };
  const approve = () => run(() => client.post(`/trip-sheets/${sheetId}/approve`), "Trip sheet approved");
  const reopen = () => {
    const reason = window.prompt(sheet.status === "APPROVED" ? "Reason for reopening this approved trip sheet:" : "Reason for returning it to the clerk:");
    if (reason && reason.trim().length >= 3) run(() => client.post(`/trip-sheets/${sheetId}/return`, { reason }), "Returned to draft");
  };
  const remove = async () => {
    if (!window.confirm("Delete this draft trip sheet?")) return;
    try { await client.delete(`/trip-sheets/${sheetId}`); nav("/trip-sheets"); } catch (e) { toast.error(apiErrorMessage(e)); }
  };
  const addExtra = async (afterId) => { if (dirty && !(await save())) return; run(() => client.post(`/trip-sheets/${sheetId}/extra-rows${afterId ? `?after_row_id=${afterId}` : ""}`), "Extra run added"); };
  const delExtra = async (id) => { if (dirty && !(await save())) return; run(() => client.delete(`/trip-sheet-rows/${id}`), "Extra run removed"); };
  const addCrew = async (role) => { if (dirty && !(await save())) return; run(() => client.post(`/trip-sheets/${sheetId}/crew`, { crew_role: role }), `${label(role)} added`); };
  const delCrew = async (id) => { if (dirty && !(await save())) return; run(() => client.delete(`/trip-sheet-crew/${id}`), "Crew entry removed"); };
  const doHandover = async () => {
    if (!handover.at_time || !handover.reason) { toast.error("Enter the change time and the reason"); return; }
    if (dirty && !(await save())) return;
    const { crew_id, ...body } = handover;
    if (await run(() => client.post(`/trip-sheet-crew/${crew_id}/handover`, body), "Crew change recorded")) setHandover(null);
  };
  const keys = useFormKeys({ onSave: () => editable && save() });
  const pick = (rowId) => {
    const el = grid.current?.querySelector(`[data-rowid="${rowId}"]`);
    el?.scrollIntoView({ block: "center" });
    el?.querySelector("input, select")?.focus();
  };

  if (!sheet || !Object.keys(rows).length) return <Spinner />;
  const s = sheet.summary;
  const km = (v) => `${Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 1 })} km`;

  return (
    <div onKeyDown={keys}>
      <PageHeader
        title={<span className="flex items-center gap-2"><Link to="/trip-sheets" className="text-slate-400 hover:text-ink"><ChevronLeft className="h-5 w-5" /></Link>
          Trip sheet · {sheet.fleet_number}{sheet.bus_change_fleet_number && <span className="font-normal text-[#8a5a00]"> → {sheet.bus_change_fleet_number}</span>} <span className="font-normal text-slate-500">· {sheet.schedule_code} v{sheet.version_number}</span> <Badge value={sheet.status} /></span>}
        subtitle={<span>{fmtDateLong(sheet.operating_date)} · {sheet.registration_number} · {sheet.schedule_name}
          {sheet.previous_closing && <> · opening odometer <b className="tabular-nums">{num(sheet.previous_closing.odometer_km)}</b> from the {fmtDate(sheet.previous_closing.operating_date)} closing</>}</span>}
        actions={<>
          {editable && <Button variant="ghost" size="sm" icon={Trash2} onClick={remove}>Delete draft</Button>}
          <Button variant="secondary" icon={ShieldCheck} onClick={validate} loading={busy}>Validate</Button>
          {editable && <Button icon={Save} onClick={save} loading={busy} disabled={!dirty} title="Ctrl+S">Save</Button>}
          {editable && <Button variant="success" icon={Send} onClick={submit} loading={busy}>Submit</Button>}
          {sheet.status === "SUBMITTED" && canIn(sheet.cost_center_id, "PUBLISHER") && <Button variant="success" icon={CheckCircle2} onClick={approve} loading={busy}>Approve</Button>}
          {((sheet.status === "SUBMITTED" && canIn(sheet.cost_center_id, "PUBLISHER")) || (sheet.status === "APPROVED" && canIn(sheet.cost_center_id, "ADMIN"))) &&
            <Button variant="secondary" icon={RotateCcw} onClick={reopen}>{sheet.status === "APPROVED" ? "Reopen" : "Return to clerk"}</Button>}
        </>} />

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Tile icon={CheckCircle2} label="Billable km" value={km(s.billable_km)} sub={`of ${km(s.planned_billable_km)} planned`} />
        <Tile icon={AlertOctagon} label="Deducted km" value={km(s.deducted_km)} sub="lost, not billed" />
        <Tile icon={AlertTriangle} label="Lost but billed" value={km(s.lost_billed_km)} sub={`attributable to ${sheet.billing_rule.bill_lost_km_attributable_to.split(",").filter(Boolean).map((x) => label(x).split(" ")[0].toLowerCase()).join(", ") || "nobody"}`} />
        <Tile swatch={TYPE_COLOR.PASSENGER_TRIP} label="Trips" value={`${s.trips_operated}/${s.trips_planned}`} sub={`${s.trips_partial} partial · ${s.trips_cancelled} cancelled`} />
        <Tile icon={Repeat} label="Odometer km" value={km(s.odometer_km)} sub="sum of entered readings" />
        <Tile icon={Wand2} label="Not entered" value={s.rows_pending} sub={dirty ? "unsaved changes" : "rows"} />
      </div>

      {scan?.from_scan && (
        <Card className="mb-3" title={<h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
          <FileScan className="h-4 w-4 text-slate-400" /> Paper sheet attached
          <span className="font-normal text-slate-500">{scan.file_name} · {scan.fields_read} boxes read
            {scan.fields_unsure ? `, ${scan.fields_unsure} could not be made out` : ""}</span>
        </h2>}>
          <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
            {/* the scanned paper itself, to read beside the entry */}
            <div className="flex flex-wrap gap-2">
              {scan.pages.map((p) => (
                <button key={p.page_no} type="button" onClick={() => setPaper(p)}
                  className="group relative w-28 overflow-hidden rounded border border-slate-200 hover:border-brand-400"
                  title={`Page ${p.page_no} - click to read it full size`}>
                  <ScanImage path={p.image_url.replace("/api", "")} alt={`Scanned page ${p.page_no}`}
                    className="h-36 w-full object-cover object-top" />
                  <span className="block bg-slate-50 py-0.5 text-center text-[11px] text-slate-600">page {p.page_no}</span>
                </button>
              ))}
            </div>
            <div>
              {scan.issues.length === 0
                ? <p className="text-sm text-[#0a6e0a]">Every box was read. Check it against the paper, then submit.</p>
                : <>
                    <p className="mb-2 text-sm text-slate-600">Fill these in from the paper, then <b>Validate</b> and submit:</p>
                    <ul className="space-y-1 text-sm">
                      {scan.issues.map((x, k) => (
                        <li key={k} className="flex items-start gap-2 text-[#8a5a00]">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{x.message}
                        </li>
                      ))}
                    </ul>
                  </>}
            </div>
          </div>
        </Card>
      )}
      <Modal open={!!paper} xwide footer={null} title={`Scanned paper · page ${paper?.page_no || ""}`} onClose={() => setPaper(null)}>
        {paper && <ScanImage path={paper.image_url.replace("/api", "")} alt={`Scanned page ${paper.page_no}`}
          className="mx-auto max-h-[75vh]" />}
      </Modal>

      {result && <Card className="mb-3"><IssueList result={result} onPick={pick} /></Card>}

      <div className="mb-3 grid gap-3 lg:grid-cols-[18rem_1fr]">
        <Card title="Paper sheet">
          <div className="space-y-3">
            <NumberInput label={`Version on paper (V in the ID line) · this date uses v${sheet.version_number}`} integer min={1} value={head.paper_version_number} disabled={!editable}
              error={head.paper_version_number && head.paper_version_number !== sheet.version_number ? `Paper is v${head.paper_version_number} - check the runs` : null}
              onChange={(v) => { setHead({ ...head, paper_version_number: v }); setDirty(true); }} />
            <div className="rounded-md border border-slate-200 p-2">
              <p className="mb-1 text-xs font-semibold text-slate-600">Bus change <span className="font-normal text-slate-400">· only if another bus ran it</span></p>
              <TextInput label="Other bus registration" value={head.bus_change_registration} disabled={!editable} list="depot-buses" placeholder="e.g. AP39WU3580"
                onChange={(e) => { setHead({ ...head, bus_change_registration: e.target.value.toUpperCase() }); setDirty(true); }}
                hint={sheet.bus_change_registration ? (sheet.bus_change_vehicle_id ? `Matched bus ${sheet.bus_change_fleet_number}` : "Not in the bus list") : undefined} />
              <datalist id="depot-buses">{(buses || []).filter((b) => b.cost_center_id === sheet.cost_center_id && b.vehicle_id !== sheet.vehicle_id)
                .map((b) => <option key={b.vehicle_id} value={b.registration_number}>{b.fleet_number}</option>)}</datalist>
              {head.bus_change_registration && <>
                <Select label="From run #" placeholder="Run the other bus started with" className="mt-2" disabled={!editable} value={head.bus_change_from_row_id ?? ""}
                  options={ordered.map((r, i) => ({ value: r.row_id, label: `${i + 1} · ${r.planned ? (r.planned.trip_number || label(r.planned.activity_type)) : "Extra run"}${r.planned ? ` ${r.planned.start_time}` : ""}` }))}
                  onChange={(v) => { setHead({ ...head, bus_change_from_row_id: v ? Number(v) : null }); setDirty(true); }} />
                <Select label="Reason" placeholder="Why the bus changed" className="mt-2" disabled={!editable} value={head.bus_change_reason_id ?? ""}
                  options={myReasons.map((x) => ({ value: x.reason_id, label: x.reason_name }))}
                  onChange={(v) => { setHead({ ...head, bus_change_reason_id: v ? Number(v) : null }); setDirty(true); }} />
              </>}
            </div>
            <TextInput label="Paper sheet no. (optional)" value={head.paper_sheet_no} disabled={!editable} onChange={(e) => { setHead({ ...head, paper_sheet_no: e.target.value }); setDirty(true); }} />
            <TextArea label="Remarks" value={head.remarks} disabled={!editable} onChange={(e) => { setHead({ ...head, remarks: e.target.value }); setDirty(true); }} />
          </div>
        </Card>
        <Card title={<span className="text-sm font-semibold">Crew <span className="font-normal text-slate-500">· {label(sheet.crew_mode)}{sheet.conductor_required ? " · conductor required" : ""}</span></span>}
          padded={false} actions={editable && <>
            <Button size="sm" variant="secondary" icon={UserPlus} onClick={() => addCrew("DRIVER")}>Driver</Button>
            <Button size="sm" variant="secondary" icon={UserPlus} onClick={() => addCrew("CONDUCTOR")}>Conductor</Button></>}>
          {sheet.roster_crew?.mismatch && (
            <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <p className="inline-flex items-center gap-1.5 font-medium">
                <UserX className="h-3.5 w-3.5" /> Not the crew the duty roster has for this bus
              </p>
              <ul className="mt-1 space-y-0.5">
                {sheet.roster_crew.rows.map((r, i) => (
                  <li key={i}>
                    {label(r.crew_role)}{r.shift_name ? ` (${r.shift_name})` : ""}: this sheet says
                    <b> {r.sheet_name}</b>, the roster has <b>{r.roster_names.join(" or ") || "nobody"}</b>
                    {r.took_over ? " (took over mid-duty)" : ""}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-amber-800">
                Keep the sheet as it happened. If the roster is what is wrong, record the change on
                the duty day screen so the two agree.
              </p>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-2 py-1.5">Role</th><th className="px-2 py-1.5">Employee</th><th className="px-2 py-1.5">Duty from</th>
                  <th className="px-2 py-1.5">Duty to</th><th className="px-2 py-1.5">Worked</th><th className="w-24" /></tr>
              </thead>
              <tbody>
                {sheet.crew.map((c) => {
                  const e = crew[c.crew_id];
                  const a = relMin(e.duty_start_day_offset, e.duty_start_time), b = relMin(e.duty_end_day_offset, e.duty_end_time);
                  return (
                    <tr key={c.crew_id} className="border-t border-slate-100 align-top">
                      <td className="px-2 py-1.5">{c.replaces_crew_id && <CornerDownRight className="mr-1 inline h-3.5 w-3.5 text-slate-400" />}{label(c.crew_role)}
                        {c.shift_name && <span className="ml-1 rounded bg-slate-100 px-1 text-[11px]">Shift {c.shift_name}</span>}
                        {c.handover_reason && <p className="text-[11px] text-slate-500">took over: {c.handover_reason}</p>}</td>
                      <td className="px-2 py-1"><Combobox options={staffOpts(c.crew_role)} value={e.employee_id} disabled={!editable} placeholder="Name or number"
                        onChange={(v) => setCrewRow(c.crew_id, { employee_id: v })} className="w-56" /></td>
                      <td className="px-2 py-1"><TimeInput value={e.duty_start_time} offset={e.duty_start_day_offset} disabled={!editable}
                        onChange={(v) => setCrewRow(c.crew_id, { duty_start_time: v })} onOffsetChange={(v) => setCrewRow(c.crew_id, { duty_start_day_offset: v })} /></td>
                      <td className="px-2 py-1"><TimeInput value={e.duty_end_time} offset={e.duty_end_day_offset} disabled={!editable}
                        onChange={(v) => setCrewRow(c.crew_id, { duty_end_time: v })} onOffsetChange={(v) => setCrewRow(c.crew_id, { duty_end_day_offset: v })} /></td>
                      <td className="px-2 py-1.5 tabular-nums text-slate-600">{a !== null && b !== null && b > a ? fmtDuration(b - a) : "—"}</td>
                      <td className="px-2 py-1 text-right whitespace-nowrap">
                        {editable && <Button size="sm" variant="ghost" icon={Repeat} title="The crew member left during duty - record who took over and when"
                          onClick={() => setHandover({ crew_id: c.crew_id, role: c.crew_role, at_day_offset: e.duty_start_day_offset, at_time: null, employee_id: null, reason: "" })}>Change</Button>}
                        {editable && <IconButton icon={Trash2} title="Remove" onClick={() => delCrew(c.crew_id)} />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card title={`Runs (${visible.length === ordered.length ? ordered.length : `${visible.length} of ${ordered.length}`})`} padded={false}
        actions={editable && <>
          <Button size="sm" variant="ghost" icon={Wand2} onClick={fillStationary}
            title="Layovers and halts take their times from the runs around them; layovers, charging and halts take SOC from the previous end and the next start">Fill in layovers & SOC</Button>
          <Button size="sm" variant="secondary" icon={Plus} onClick={() => addExtra(null)}>Extra run</Button>
        </>}>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 px-4 py-2 text-xs">
          <span className="mr-1 text-slate-500">Show</span>
          {GROUPS.map(([g, name]) => {
            const n = ordered.filter((r) => groupOf(r) === g).length;
            if (!n) return null;
            const off = filter.hidden.has(g);
            const sw = g === "EXTRA" ? "#64748b" : g === "PAYABLE" ? TYPE_COLOR.NON_REVENUE_MOVEMENT : TYPE_COLOR[g];
            return (
              <button key={g} type="button" tabIndex={-1} aria-pressed={!off} onClick={() => toggleGroup(g)}
                className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 ring-1 ${off ? "text-slate-400 line-through ring-slate-200" : "text-slate-700 ring-slate-300 hover:bg-slate-50"}`}>
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: off ? "#cbd5e1" : sw }} />{name}<span className="tabular-nums text-slate-400">{n}</span>
              </button>
            );
          })}
          <label className="ml-2 flex items-center gap-1.5 text-slate-600">
            <input type="checkbox" className="h-3.5 w-3.5 rounded border-slate-300" checked={filter.pendingOnly} onChange={(e) => saveFilter({ ...filter, pendingOnly: e.target.checked })} />
            Not entered only
          </label>
          {(filter.hidden.size > 0 || filter.pendingOnly) && <button type="button" tabIndex={-1} className="ml-1 text-brand-600 hover:underline" onClick={() => saveFilter({ hidden: new Set(), pendingOnly: false })}>Show all</button>}
        </div>
        <div ref={grid} className="overflow-x-auto" onKeyDown={gridArrows}>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-2 py-1.5">Run</th><th className="px-2 py-1.5">Planned</th><th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5">Departed</th><th className="px-2 py-1.5">Arrived</th>
                <th className="px-2 py-1.5">Odo start</th><th className="px-2 py-1.5">Odo end</th><th className="px-2 py-1.5 text-right">Odo km</th>
                <th className="px-2 py-1.5">SOC %</th><th className="px-2 py-1.5 text-right">Billed</th><th className="w-16" /></tr>
            </thead>
            <tbody>
              {visible.length === 0 && <tr><td colSpan={11} className="px-4 py-6 text-center text-xs text-slate-400">No runs match the filter</td></tr>}
              {visible.map((r, i) => {
                const e = rows[r.row_id];
                const p = r.planned;
                const type = p?.activity_type;
                const driving = !p || ["PASSENGER_TRIP", "NON_REVENUE_MOVEMENT"].includes(type);
                const lost = e.status === "PARTIAL" || e.status === "CANCELLED";
                const off = e.status === "CANCELLED";
                const odoKm = e.start_odometer_km !== null && e.end_odometer_km !== null ? e.end_odometer_km - e.start_odometer_km : null;
                const expect = e.status === "OPERATED" ? p?.planned_km : null;
                const devBad = odoKm !== null && expect ? Math.abs(odoKm - expect) / expect * 100 > tol : false;
                const a = relMin(e.actual_start_day_offset, e.actual_start_time), b = relMin(e.actual_end_day_offset, e.actual_end_time);
                const late = p && a !== null ? a - p.start_min : null;
                return (
                  <Fragment key={r.row_id}>
                    <tr data-rowid={r.row_id} className={`border-t border-slate-100 align-top ${off ? "bg-danger/5" : e.status === "PENDING" ? "" : e.status === "PARTIAL" ? "bg-warn/5" : ""}`}>
                      <td className="px-2 py-1.5">
                        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: p ? TYPE_COLOR[type] : "#64748b" }} />
                          {p ? <b>{p.trip_number || label(type)}</b> : <b>Extra run</b>}
                          {p?.trip_number && <span className="text-xs text-slate-500">{p.route_code} {p.direction_code}</span>}
                          {p?.stops && <button type="button" tabIndex={-1} className="text-slate-400 hover:text-ink" title="Stop times and odometer"
                            onClick={() => setOpen((o) => ({ ...o, [r.row_id]: !o[r.row_id] }))}>{open[r.row_id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button>}
                        </span>
                        {p ? <p className="text-xs text-slate-500">{p.origin_name}{p.origin_code !== p.destination_code && ` → ${p.destination_name}`}</p> : (
                          <div className="mt-1 flex flex-col gap-1">
                            <Combobox options={locOptions(locs)} value={e.extra_from_location_id} disabled={!editable} placeholder="From" onChange={(v) => setRow(r.row_id, { extra_from_location_id: v })} className="w-40" />
                            <Combobox options={locOptions(locs)} value={e.extra_to_location_id} disabled={!editable} placeholder="To" onChange={(v) => setRow(r.row_id, { extra_to_location_id: v })} className="w-40" />
                            <Checkbox label="Payable" checked={e.extra_payable} onChange={(v) => editable && setRow(r.row_id, { extra_payable: v })} />
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap text-xs tabular-nums text-slate-500">
                        {p ? <>{fmtRel(p.start_min)} → {fmtRel(p.end_min)}<br />{p.planned_km ? `${p.planned_km} km` : fmtDuration(p.end_min - p.start_min)}
                          {p.payability_status === "PAYABLE" && <Badge value="PAYABLE" className="ml-1">payable</Badge>}</> : "unplanned"}
                      </td>
                      <td className="min-w-[11rem] px-1.5 py-1" data-row={i} data-col="status">
                        <div className="flex items-center gap-1">
                          <Select options={options(p?.trip_number ? STATUSES : STATUSES.filter((x) => x !== "PARTIAL"))} value={e.status} disabled={!editable}
                            onChange={(v) => setRow(r.row_id, { status: v })} className="w-[8.75rem]" />
                          {editable && p && <IconButton icon={Wand2} title="Ran to plan: fill status, planned times and start odometer" onClick={() => asPlanned(r)} />}
                        </div>
                      </td>
                      {off ? <td colSpan={6} className="px-2 py-1.5 text-xs text-slate-400">Cancelled - no actuals</td> : (
                        <>
                          <td className="min-w-[7.75rem] px-1.5 py-1" data-row={i} data-col="out"><TimeInput value={e.actual_start_time} offset={e.actual_start_day_offset} disabled={!editable} suggest={p?.start_time}
                            onChange={(v) => setRow(r.row_id, { actual_start_time: v })} onOffsetChange={(v) => setRow(r.row_id, { actual_start_day_offset: v })} />
                            {late !== null && late !== 0 && <p className={`text-[11px] ${late > 0 ? "text-[#8a5a00]" : "text-slate-500"}`}>{late > 0 ? `${fmtDuration(late)} late` : `${fmtDuration(-late)} early`}</p>}</td>
                          <td className="min-w-[7.75rem] px-1.5 py-1" data-row={i} data-col="in"><TimeInput value={e.actual_end_time} offset={e.actual_end_day_offset} disabled={!editable} suggest={p?.end_time}
                            onChange={(v) => setRow(r.row_id, { actual_end_time: v })} onOffsetChange={(v) => setRow(r.row_id, { actual_end_day_offset: v })} />
                            {a !== null && b !== null && b <= a && <p className="text-[11px] text-danger">before departure</p>}</td>
                          <td className="min-w-[5.75rem] px-1.5 py-1" data-row={i} data-col="os">{driving && <NumberInput integer min={0} value={e.start_odometer_km} disabled={!editable} placeholder={prevEndOdo(r.row_id) ?? ""}
                            onChange={(v) => setRow(r.row_id, { start_odometer_km: v })} className="w-[5.25rem]" />}</td>
                          <td className="min-w-[5.75rem] px-1.5 py-1" data-row={i} data-col="oe">{driving && <NumberInput integer min={0} value={e.end_odometer_km} disabled={!editable}
                            onChange={(v) => setRow(r.row_id, { end_odometer_km: v })} className="w-[5.25rem]" />}</td>
                          <td className={`px-2 py-1.5 text-right tabular-nums ${devBad || (odoKm !== null && odoKm < 0) ? "font-semibold text-danger" : "text-slate-600"}`}>
                            {odoKm !== null ? odoKm.toFixed(1) : "—"}</td>
                          <td className="min-w-[8rem] px-1.5 py-1" data-row={i} data-col="soc">
                            <div className="flex items-center gap-1">
                              <NumberInput min={0} max={100} value={e.start_soc_pct} disabled={!editable} onChange={(v) => setRow(r.row_id, { start_soc_pct: v })} className="w-12" />
                              <span className="text-slate-400">→</span>
                              <NumberInput min={0} max={100} value={e.end_soc_pct} disabled={!editable} onChange={(v) => setRow(r.row_id, { end_soc_pct: v })} className="w-12" />
                            </div>
                            {type === "CHARGING" && <NumberInput min={0} value={e.energy_kwh} disabled={!editable} suffix="kWh" onChange={(v) => setRow(r.row_id, { energy_kwh: v })} className="mt-1 w-28" />}
                          </td>
                        </>
                      )}
                      <td className="px-2 py-1.5 text-right tabular-nums" title="Billed km as last saved">
                        {r.billing.billable ? <>{r.billing.billable_km}{r.billing.lost_km > 0 && <p className="text-[11px] text-slate-500">−{(r.billing.lost_km - r.billing.lost_billed_km).toFixed(1)}</p>}</> : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-1 py-1 whitespace-nowrap">
                        {editable && <IconButton icon={Plus} title="Add an extra run after this one" onClick={() => addExtra(r.row_id)} />}
                        {editable && r.is_extra && <IconButton icon={Trash2} title="Remove extra run" onClick={() => delExtra(r.row_id)} />}
                      </td>
                    </tr>
                    {lost && (
                      <tr className={off ? "bg-danger/5" : "bg-warn/5"}>
                        <td />
                        <td colSpan={10} className="px-2 pb-2">
                          <div className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="font-medium text-slate-600">{off ? "Cancelled" : "Cut short"}:</span>
                            <Select placeholder="Reason" options={myReasons.map((x) => ({ value: x.reason_id, label: x.reason_name }))} value={e.reason_id ?? ""} disabled={!editable}
                              onChange={(v) => { const rr = myReasons.find((x) => String(x.reason_id) === String(v)); setRow(r.row_id, { reason_id: v ? Number(v) : null, attributable_to: e.attributable_to || rr?.default_attributable_to || null }); }} className="w-52" />
                            <span className="text-slate-500">attributable to</span>
                            <Select placeholder="Who caused it" options={options(ATTR)} value={e.attributable_to ?? ""} disabled={!editable}
                              onChange={(v) => setRow(r.row_id, { attributable_to: v })} className="w-60" />
                            {e.status === "PARTIAL" && p?.stops && (
                              <>
                                <span className="text-slate-500">ended at</span>
                                <Select placeholder="Last stop reached" disabled={!editable} value={e.stopped_at_route_stop_id ?? ""}
                                  options={p.stops.slice(0, -1).map((st) => ({ value: st.route_stop_id, label: `${st.location_name} · ${st.cumulative_km} km` }))}
                                  onChange={(v) => setRow(r.row_id, { stopped_at_route_stop_id: v ? Number(v) : null })} className="w-48" />
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                    {open[r.row_id] && p?.stops && (
                      <tr className="border-t border-dashed border-slate-200 bg-slate-50/60">
                        <td colSpan={11} className="px-6 py-2">
                          <table className="text-xs">
                            <thead className="text-left uppercase tracking-wide text-slate-500"><tr><th className="pr-3">Stop</th><th className="pr-3">km</th><th className="pr-3">Planned</th>
                              <th className="pr-3">Arrived</th><th className="pr-3">Departed</th><th className="pr-3">Odometer</th><th className="pr-3">SOC %</th></tr></thead>
                            <tbody>
                              {p.stops.map((st, k) => {
                                const se = e.stops[k];
                                const setStop = (patch) => setRow(r.row_id, { stops: e.stops.map((x, j) => (j === k ? { ...x, ...patch } : x)) });
                                return (
                                  <tr key={st.scheduled_stop_time_id}>
                                    <td className="pr-3 py-0.5 font-medium">{st.location_name}</td>
                                    <td className="pr-3 tabular-nums text-slate-500">{st.cumulative_km}</td>
                                    <td className="pr-3 tabular-nums text-slate-500">{st.arrival || "—"} / {st.departure || "—"}</td>
                                    <td className="pr-3">{k > 0 && <TimeInput value={se.arrival_time} offset={se.arrival_day_offset} disabled={!editable} suggest={st.arrival}
                                      onChange={(v) => setStop({ arrival_time: v })} onOffsetChange={(v) => setStop({ arrival_day_offset: v })} />}</td>
                                    <td className="pr-3">{k < p.stops.length - 1 && <TimeInput value={se.departure_time} offset={se.departure_day_offset} disabled={!editable} suggest={st.departure}
                                      onChange={(v) => setStop({ departure_time: v })} onOffsetChange={(v) => setStop({ departure_day_offset: v })} />}</td>
                                    <td className="pr-3"><NumberInput integer min={0} value={se.odometer_km} disabled={!editable} onChange={(v) => setStop({ odometer_km: v })} className="w-24" /></td>
                                    <td className="pr-3"><NumberInput min={0} max={100} value={se.soc_pct} disabled={!editable} onChange={(v) => setStop({ soc_pct: v })} className="w-16" /></td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400">
          Wand = ran to plan · Enter moves across · ↑↓ between runs · Ctrl+S saves · Billed km update after saving.
          Lost km are billed when attributable to: {sheet.billing_rule.bill_lost_km_attributable_to.split(",").filter(Boolean).map((x) => label(x).split(" ")[0]).join(", ") || "nobody"} (cost-center setting).
        </p>
      </Card>

      <Modal open={!!handover} title={`${label(handover?.role || "DRIVER")} change`} onClose={() => setHandover(null)} onSave={doHandover}>
        {handover && (
          <div className="grid gap-3">
            <p className="text-sm text-slate-600">The current {label(handover.role).toLowerCase()} leaves at this time; their working time ends there and the replacement takes over until the original duty end.</p>
            <TimeInput label="Change time" required value={handover.at_time} offset={handover.at_day_offset}
              onChange={(v) => setHandover({ ...handover, at_time: v })} onOffsetChange={(v) => setHandover({ ...handover, at_day_offset: v })} />
            <Combobox label={`New ${label(handover.role).toLowerCase()}`} options={staffOpts(handover.role)} value={handover.employee_id}
              onChange={(v) => setHandover({ ...handover, employee_id: v })} placeholder="Name or number" />
            <TextArea label="Reason" value={handover.reason} onChange={(e) => setHandover({ ...handover, reason: e.target.value })} />
          </div>
        )}
      </Modal>
    </div>
  );
}
