import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertOctagon, AlertTriangle, ArrowDown, ArrowUp, BatteryCharging, BusFront, CheckCircle2, ChevronLeft, CopyPlus, Lock,
  Moon, Pencil, Printer, Send, ShieldCheck, Trash2, Truck, Undo2, Users2, Hourglass, Warehouse, Wand2,
} from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Spinner } from "../components/ui";
import { Checkbox, DateInput, TextArea, TextInput } from "../components/inputs";
import ActivityEditor, { newActivity, toEditor } from "../components/ActivityEditor";
import ScheduleGantt from "../components/viz/ScheduleGantt";
import SocProfile from "../components/viz/SocProfile";
import SummaryTiles from "../components/viz/SummaryTiles";
import BusUsage from "../components/viz/BusUsage";
import CrewCard from "../components/CrewCard";
import { TYPE_COLOR } from "../components/viz/colors";
import { addDays, fmtDate, fmtDuration, fmtRel, label, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

const ADD = [
  { type: "PASSENGER_TRIP", label: "Passenger trip", key: "t", icon: Users2 },
  { type: "NON_REVENUE_MOVEMENT", label: "Movement", key: "m", icon: Truck },
  { type: "CHARGING", label: "Charging", key: "c", icon: BatteryCharging },
  { type: "LAYOVER", label: "Layover", key: "l", icon: Hourglass },
  { type: "HALT", label: "Halt", key: "h", icon: Warehouse },
];

function detailText(a) {
  if (a.trip) return `${a.trip.trip_number} · ${a.trip.route_code} ${a.trip.direction_code} · ${a.trip.stops.length} stops`;
  if (a.movement) return `${label(a.movement.movement_purpose)}`;
  if (a.charging) return a.charging.planned_start_soc_pct !== null && a.charging.planned_end_soc_pct !== null ? `SOC ${Number(a.charging.planned_start_soc_pct)}% → ${Number(a.charging.planned_end_soc_pct)}%` : "Charging session";
  if (a.halt) return a.halt.planned_start_soc_pct !== null && a.halt.planned_end_soc_pct !== null ? `Off service · SOC ${Number(a.halt.planned_start_soc_pct)}% → ${Number(a.halt.planned_end_soc_pct)}%` : "Off service";
  if (a.layover) return a.layover.planned_start_soc_pct !== null && a.layover.planned_end_soc_pct !== null ? `${label(a.layover.layover_purpose)} · SOC ${Number(a.layover.planned_start_soc_pct)}% → ${Number(a.layover.planned_end_soc_pct)}%` : label(a.layover.layover_purpose);
  return "";
}

function IssueList({ result, onPick }) {
  if (!result) return null;
  const errs = result.issues.filter((i) => i.severity === "ERROR");
  const warns = result.issues.filter((i) => i.severity === "WARNING");
  if (!result.issues.length) {
    return <p className="flex items-center gap-2 text-sm font-medium text-[#0a6e0a]"><CheckCircle2 className="h-4 w-4" /> No errors or warnings - ready to publish</p>;
  }
  const row = (i, k) => (
    <li key={k}>
      <button type="button" disabled={!i.activity_id} onClick={() => onPick?.(i.activity_id)}
        className="flex w-full items-start gap-2 rounded px-2 py-1 text-left text-sm hover:bg-slate-50 disabled:hover:bg-transparent">
        {i.severity === "ERROR" ? <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#b07800]" />}
        <span><span className="text-ink">{i.message}</span> <span className="text-[11px] text-slate-400">{i.code}</span></span>
      </button>
    </li>
  );
  return (
    <div className="space-y-2">
      <p className="flex gap-3 text-sm">
        <span className="inline-flex items-center gap-1 font-medium text-danger"><AlertOctagon className="h-4 w-4" />{errs.length} error{errs.length !== 1 && "s"}</span>
        <span className="inline-flex items-center gap-1 font-medium text-[#8a5a00]"><AlertTriangle className="h-4 w-4" />{warns.length} warning{warns.length !== 1 && "s"}</span>
        <span className="text-xs text-slate-500">Errors block publishing; warnings need acknowledgement.</span>
      </p>
      <ul className="max-h-72 overflow-auto">{errs.map(row)}{warns.map((i, k) => row(i, `w${k}`))}</ul>
    </div>
  );
}

export default function ScheduleBuilder() {
  const { scheduleId, versionId } = useParams();
  const nav = useNavigate();
  const { canIn, companyOf } = useAuth();
  const toast = useToast();
  const { data: schedule, reload: reloadSchedule } = useApi(`/schedules/${scheduleId}`);
  // rights and pickable masters follow the schedule's own cost center (it may be opened from the All view)
  const can = (role) => !!schedule && canIn(schedule.cost_center_id, role);
  const { data: allLocs = [] } = useApi("/locations", []);
  const { data: allRoutes = [] } = useApi("/routes", []);
  const routes = (allRoutes || []).filter((r) => !schedule || r.cost_center_id === schedule.cost_center_id);
  const company = schedule ? companyOf(schedule.cost_center_id) : null;
  const locs = (allLocs || []).filter((l) => company === null || l.company_id === company);
  const { data: settings } = useApi("/settings");
  const vid = versionId || (schedule && (schedule.versions.find((v) => v.status === "DRAFT") || schedule.versions[schedule.versions.length - 1])?.schedule_version_id);
  const { data: version, reload: reloadVersion, setData: setVersion } = useApi(vid ? `/schedule-versions/${vid}` : null);
  const [editor, setEditor] = useState(null);
  const [selected, setSelected] = useState(null);
  const [validation, setValidation] = useState(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [newVersion, setNewVersion] = useState(null);
  const [headerForm, setHeaderForm] = useState(null);
  const [busLanes, setBusLanes] = useState([]);
  const gridRef = useRef(null);
  const isDraft = version?.status === "DRAFT";
  const canEdit = isDraft && can("SCHEDULER");
  const acts = useMemo(() => version?.activities || [], [version]);
  const gapWarn = Number(settings?.values?.gap_warn_minutes ?? 30);

  const reloadAll = useCallback(async () => { await reloadVersion(); reloadSchedule(); setValidation(null); }, [reloadVersion, reloadSchedule]);

  const openNew = useCallback((type) => {
    if (!canEdit) return;
    const prev = acts[acts.length - 1];
    setEditor(newActivity(type, prev, acts));
  }, [acts, canEdit]);
  const openEdit = (a) => setEditor(toEditor(a, routes));

  const validate = useCallback(async (quiet) => {
    if (!vid) return null;
    try {
      const { data } = await client.post(`/schedule-versions/${vid}/validate`);
      setValidation(data);
      if (!quiet) toast[data.valid ? "ok" : "error"](data.valid ? `Valid · ${data.warning_count} warning(s)` : `${data.error_count} error(s) found`);
      return data;
    } catch (e) {
      toast.error(apiErrorMessage(e));
      return null;
    }
  }, [vid, toast]);

  // page shortcuts: Alt+T/M/C/L add, Alt+V validate, Alt+P publish
  useEffect(() => {
    const h = (e) => {
      if (!e.altKey || editor || publishOpen) return;
      const k = e.code.replace("Key", "").toLowerCase();
      const add = ADD.find((x) => x.key === k);
      if (add) { e.preventDefault(); openNew(add.type); }
      if (k === "v") { e.preventDefault(); validate(); }
      if (k === "p" && isDraft && can("PUBLISHER")) { e.preventDefault(); openPublish(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const openPublish = async () => {
    await validate(true);
    setPublishOpen(true);
    // bus usage: this version + other published schedules on the same bus
    try {
      const { data: same } = await client.get(`/schedules?vehicle_id=${schedule.vehicle_id}`);
      const lanes = [{ key: "me", label: `${schedule.schedule_code} v${version.version_number}`, start_min: version.summary.cycle_start_min, end_min: version.summary.cycle_end_min, current: true }];
      for (const s of same) {
        if (s.schedule_id === schedule.schedule_id || s.status === "RETIRED") continue;
        for (const v of s.versions.filter((x) => x.status === "PUBLISHED")) {
          const { data: d } = await client.get(`/schedule-versions/${v.schedule_version_id}`);
          lanes.push({ key: `v${v.schedule_version_id}`, label: `${s.schedule_code} v${v.version_number}`, start_min: d.summary.cycle_start_min, end_min: d.summary.cycle_end_min });
        }
      }
      setBusLanes(lanes);
    } catch {
      setBusLanes([]);
    }
  };

  const move = async (idx, dir) => {
    const ids = acts.map((a) => a.activity_id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    try {
      const { data } = await client.post(`/schedule-versions/${vid}/activities/reorder`, { activity_ids: ids });
      setVersion(data);
      setValidation(null);
      setTimeout(() => gridRef.current?.querySelector(`[data-act="${ids[j]}"]`)?.focus(), 30);
    } catch (e) {
      toast.error(apiErrorMessage(e));
    }
  };
  const remove = async (a) => {
    if (!window.confirm(`Remove #${a.sequence_number} ${label(a.activity_type)}?`)) return;
    try {
      await client.delete(`/activities/${a.activity_id}`);
      toast.ok("Activity removed");
      reloadAll();
    } catch (e) {
      toast.error(apiErrorMessage(e));
    }
  };
  const onSaved = async (saved, andNext) => {
    const { data } = await client.get(`/schedule-versions/${vid}`);
    setVersion(data);
    setValidation(null);
    setSelected(saved.activity_id);
    if (andNext) {
      const sorted = data.activities;
      setEditor(newActivity(saved.activity_type, sorted[sorted.length - 1], sorted));
    } else {
      setEditor(null);
      setTimeout(() => gridRef.current?.querySelector(`[data-act="${saved.activity_id}"]`)?.focus(), 50);
    }
  };

  if (!schedule || !version) return <Spinner />;
  const pickIssue = (id) => {
    const a = acts.find((x) => x.activity_id === id);
    setSelected(id);
    setPublishOpen(false);
    if (a) openEdit(a);
  };
  const issuesFor = (id) => (validation?.issues || []).filter((i) => i.activity_id === id);
  const latest = schedule.versions[schedule.versions.length - 1];
  const hasDraft = schedule.versions.some((v) => v.status === "DRAFT");
  const neverPublished = schedule.versions.every((v) => v.status === "DRAFT");
  const unpublish = async () => {
    if (!window.confirm(`Unpublish v${version.version_number}? It becomes an editable draft and stops applying until it is published again.${version.version_number > 1 ? " The previous version goes back to live." : ""}`)) return;
    try {
      await client.post(`/schedule-versions/${vid}/unpublish`);
      toast.ok(`v${version.version_number} is a draft again`);
      reloadAll();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };
  const fillLayovers = async () => {
    if (!window.confirm("Fill in layovers and SOC?\n\n- Layovers, charging and halts take their start SOC from the previous activity's end SOC and their end SOC from the next activity's start SOC.\n- Every layover starts when the previous activity ends and ends when the next starts (charging and halts keep their times).\n- Idle gaps at one location become new layovers.\n- Gaps next to a halt, or where the bus changes location, are left alone.")) return;
    try {
      const { data } = await client.post(`/schedule-versions/${vid}/fill-layovers`);
      setVersion(data.version);
      setValidation(null);
      const r = data.result;
      toast.ok(`${r.created} layover${r.created === 1 ? "" : "s"} added, ${r.updated} updated · SOC filled on ${r.charging_updated} charging, ${r.halt_updated} halt${r.halt_updated === 1 ? "" : "s"}`);
      if (r.skipped.length) toast.error(`Not filled: ${r.skipped.join("; ")}`);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };
  const deleteSchedule = async () => {
    if (!window.confirm(`Delete schedule ${schedule.schedule_code} and all its activities? This cannot be undone.`)) return;
    try {
      await client.delete(`/schedules/${scheduleId}`);
      toast.ok(`Schedule ${schedule.schedule_code} deleted`);
      nav("/schedules");
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  // grid with day separators, gaps and overlaps between rows
  let prevEnd = null;
  let prevDay = null;
  const rows = acts.map((a, idx) => {
    const day = Math.floor(a.start_min / 1440);
    const between = [];
    if (prevDay === null ? day > 0 : day !== prevDay) between.push({ kind: "day", day });
    if (prevEnd !== null && a.start_min < prevEnd) between.push({ kind: "overlap", min: prevEnd - a.start_min });
    else if (prevEnd !== null && a.start_min - prevEnd > 0) between.push({ kind: a.start_min - prevEnd > gapWarn ? "gap" : "idle", min: a.start_min - prevEnd });
    prevEnd = Math.max(prevEnd ?? -Infinity, a.end_min);
    prevDay = day;
    return { a, idx, between };
  });

  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-2"><Link to="/schedules" className="text-slate-400 hover:text-ink"><ChevronLeft className="h-5 w-5" /></Link>{schedule.schedule_code} <span className="font-normal text-slate-500">· {schedule.schedule_name}</span></span>}
        subtitle={<span className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="inline-flex items-center gap-1"><BusFront className="h-4 w-4" /> {schedule.fleet_number} ({schedule.registration_number})</span>
          <span>Daily · effective {fmtDate(schedule.effective_from)} → {schedule.effective_to ? fmtDate(schedule.effective_to) : "open"}</span>
          <span>{schedule.timezone}</span>
          <Badge value={schedule.status} />
        </span>}
        actions={<>
          {can("SCHEDULER") && <Button variant="ghost" size="sm" icon={Pencil} onClick={() => setHeaderForm({ schedule_name: schedule.schedule_name, effective_from: schedule.effective_from, effective_to: schedule.effective_to })}>Edit header</Button>}
          <Button variant="secondary" icon={Printer} onClick={() => window.open(`/print/${vid}`, "_blank")}>Print</Button>
          <Button variant="secondary" icon={ShieldCheck} onClick={() => validate()} title="Alt+V">Validate</Button>
          {isDraft && can("PUBLISHER") && <Button variant="success" icon={Send} onClick={openPublish} title="Alt+P">Publish…</Button>}
          {version.status === "PUBLISHED" && !hasDraft && can("PUBLISHER") && <Button variant="secondary" icon={Undo2} onClick={unpublish}>Unpublish & edit</Button>}
          {!hasDraft && can("SCHEDULER") && schedule.status !== "RETIRED" && (
            <Button icon={CopyPlus} onClick={() => setNewVersion({ valid_from: addDays(latest.valid_from > todayIso() ? latest.valid_from : todayIso(), 1), change_reason: "" })}>New version</Button>
          )}
        </>} />

      {/* versions */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {schedule.versions.map((v) => (
          <button key={v.schedule_version_id} onClick={() => nav(`/schedules/${scheduleId}/v/${v.schedule_version_id}`)}
            className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-xs ${String(v.schedule_version_id) === String(vid) ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
            <span className="font-semibold">v{v.version_number}</span>
            <Badge value={v.effective_status} />
            <span className="tabular-nums text-slate-500">{fmtDate(v.valid_from)} → {v.valid_to ? fmtDate(v.valid_to) : "open"}</span>
          </button>
        ))}
        {!isDraft && <span className="inline-flex items-center gap-1 text-xs text-slate-500"><Lock className="h-3.5 w-3.5" /> Published versions are read-only. Create a new version to revise{version.status === "PUBLISHED" && can("PUBLISHER") ? ", or unpublish to edit this one" : ""}.</span>}
        {isDraft && can("SCHEDULER") && (
          <span className="ml-auto flex items-center gap-2 text-xs">
            Valid from <DateInput compact value={version.valid_from} onChange={async (v) => { if (!v) return; try { await client.put(`/schedule-versions/${vid}`, { valid_from: v }); reloadAll(); } catch (e) { toast.error(apiErrorMessage(e)); } }} />
            {version.version_number > 1 && <Button size="sm" variant="ghost" icon={Trash2} onClick={async () => {
              if (!window.confirm("Delete this draft version?")) return;
              await client.delete(`/schedule-versions/${vid}`);
              nav(`/schedules/${scheduleId}`); reloadSchedule();
            }}>Delete draft</Button>}
            {neverPublished && <Button size="sm" variant="ghost" icon={Trash2} onClick={deleteSchedule}>Delete schedule</Button>}
          </span>
        )}
      </div>

      <div className="space-y-4">
        <SummaryTiles summary={version.summary} />

        <Card title={`Operating cycle · v${version.version_number}`} actions={<span className="text-xs text-slate-500">Hover for details · click a bar to edit</span>}>
          <ScheduleGantt activities={acts} operatingDate={version.valid_from} gapWarn={gapWarn} selectedId={selected}
            onSelect={(id) => { setSelected(id); const a = acts.find((x) => x.activity_id === id); if (a) openEdit(a); }} />
        </Card>

        <Card title={`Activities (${acts.length})`} padded={false}
          actions={canEdit && <>
            {ADD.map((b) => (
              <Button key={b.type} size="sm" variant="secondary" onClick={() => openNew(b.type)} title={`Alt+${b.key.toUpperCase()}`}>
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: TYPE_COLOR[b.type] }} />{b.label}
                <kbd className="ml-1 rounded bg-slate-100 px-1 text-[10px] text-slate-500">Alt+{b.key.toUpperCase()}</kbd>
              </Button>
            ))}
            {acts.length > 1 && <Button size="sm" variant="ghost" icon={Wand2} onClick={fillLayovers}
              title="Carry SOC into layovers, charging and halts from the activities around them, snap layover times, and fill idle gaps with layovers">Fill in layovers & SOC</Button>}
          </>}>
          <div className="overflow-x-auto" ref={gridRef}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <th className="w-10 px-3 py-2">#</th><th className="px-2 py-2">Type</th><th className="px-2 py-2">From → To</th>
                  <th className="px-2 py-2">Start</th><th className="px-2 py-2">End</th><th className="px-2 py-2 text-right">Duration</th>
                  <th className="px-2 py-2 text-right">km</th><th className="px-2 py-2">Details</th><th className="px-2 py-2" /><th className="w-32" />
                </tr>
              </thead>
              <tbody>
                {acts.length === 0 && (
                  <tr><td colSpan={10} className="px-4 py-10 text-center text-sm text-slate-400">
                    {canEdit ? <>Start with the first movement out of the depot: press <kbd className="rounded border px-1">Alt+M</kbd>, or <kbd className="rounded border px-1">Alt+T</kbd> for a passenger trip.</> : "No activities"}
                  </td></tr>
                )}
                {rows.map(({ a, idx, between }) => {
                  const iss = issuesFor(a.activity_id);
                  const hasErr = iss.some((i) => i.severity === "ERROR");
                  const crosses = Math.floor(a.end_min / 1440) > Math.floor(a.start_min / 1440);
                  return (
                    <Fragment key={a.activity_id}>
                      {between.map((b, k) => (
                        <tr key={k}>
                          <td colSpan={10} className={`px-3 py-1 text-[11px] font-medium ${b.kind === "day" ? "bg-ink/5 text-ink" : b.kind === "overlap" ? "bg-danger/10 text-danger" : b.kind === "gap" ? "bg-warn/15 text-[#8a5a00]" : "text-slate-400"}`}>
                            {b.kind === "day" && <span className="inline-flex items-center gap-1"><Moon className="h-3.5 w-3.5" /> Day {b.day + 1} · {fmtDate(addDays(version.valid_from, b.day))}</span>}
                            {b.kind === "overlap" && <span className="inline-flex items-center gap-1"><AlertOctagon className="h-3.5 w-3.5" /> Overlap {fmtDuration(b.min)}</span>}
                            {b.kind === "gap" && <span className="inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" /> Unexplained gap {fmtDuration(b.min)} - add a layover?</span>}
                            {b.kind === "idle" && <span>· {fmtDuration(b.min)} idle</span>}
                          </td>
                        </tr>
                      ))}
                      <tr data-act={a.activity_id} tabIndex={0}
                        onClick={() => { setSelected(a.activity_id); openEdit(a); }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { e.preventDefault(); openEdit(a); }
                          else if (e.altKey && e.key === "ArrowUp" && canEdit) { e.preventDefault(); move(idx, -1); }
                          else if (e.altKey && e.key === "ArrowDown" && canEdit) { e.preventDefault(); move(idx, 1); }
                          else if (e.key === "ArrowDown") { e.preventDefault(); e.currentTarget.parentElement.querySelectorAll("tr[data-act]")[idx + 1]?.focus(); }
                          else if (e.key === "ArrowUp") { e.preventDefault(); e.currentTarget.parentElement.querySelectorAll("tr[data-act]")[idx - 1]?.focus(); }
                          else if (e.key === "Delete" && canEdit) { e.preventDefault(); remove(a); }
                        }}
                        onFocus={() => setSelected(a.activity_id)}
                        className={`cursor-pointer border-b border-slate-100 outline-none hover:bg-brand-50/40 focus:bg-brand-50 ${selected === a.activity_id ? "bg-brand-50/60" : ""} ${hasErr ? "border-l-4 border-l-danger" : ""}`}>
                        <td className="px-3 py-2 tabular-nums text-slate-500">{a.sequence_number}</td>
                        <td className="px-2 py-2"><span className="inline-flex items-center gap-1.5 whitespace-nowrap"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: TYPE_COLOR[a.activity_type] }} />{label(a.activity_type)}</span></td>
                        <td className="px-2 py-2 whitespace-nowrap">{a.origin_name === a.destination_name ? a.origin_name : <>{a.origin_name} <span className="text-slate-400">→</span> {a.destination_name}</>}</td>
                        <td className="px-2 py-2 tabular-nums whitespace-nowrap">{fmtRel(a.start_min)}</td>
                        <td className="px-2 py-2 tabular-nums whitespace-nowrap">{fmtRel(a.end_min)} {crosses && <Moon className="inline h-3.5 w-3.5 text-brand-600" aria-label="crosses midnight" />}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtDuration(a.end_min - a.start_min)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{a.distance_km ? a.distance_km : ""}</td>
                        <td className="px-2 py-2 text-xs text-slate-600">{detailText(a)}</td>
                        <td className="px-2 py-2">{a.movement && <Badge value={a.movement.payability_status} />}
                          {iss.length > 0 && <span className={`ml-1 inline-flex items-center gap-0.5 text-[11px] ${hasErr ? "text-danger" : "text-[#8a5a00]"}`} title={iss.map((i) => i.message).join("\n")}>
                            {hasErr ? <AlertOctagon className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}{iss.length}</span>}</td>
                        <td className="whitespace-nowrap px-2 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                          {canEdit && (
                            <>
                              <IconButton icon={ArrowUp} title="Move up (Alt+↑)" disabled={idx === 0} onClick={() => move(idx, -1)} />
                              <IconButton icon={ArrowDown} title="Move down (Alt+↓)" disabled={idx === acts.length - 1} onClick={() => move(idx, 1)} />
                              <IconButton icon={Pencil} title="Edit (Enter)" onClick={() => openEdit(a)} />
                              <IconButton icon={Trash2} title="Remove (Delete)" onClick={() => remove(a)} />
                            </>
                          )}
                        </td>
                      </tr>
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {acts.length > 0 && <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400">↑↓ move between rows · Enter edit · Alt+↑/↓ reorder · Delete remove · Alt+V validate{can("PUBLISHER") ? " · Alt+P publish" : ""}</p>}
        </Card>

        <CrewCard version={version} canEdit={canEdit} locs={locs} onSaved={(v) => { setVersion(v); reloadSchedule(); setValidation(null); }} />

        <Card title="Planned state of charge"><SocProfile activities={acts} /></Card>
        <div>
          <Card title="Validation" actions={<Button size="sm" variant="secondary" icon={ShieldCheck} onClick={() => validate()}>Run</Button>}>
            {validation ? <IssueList result={validation} onPick={pickIssue} /> : <p className="text-sm text-slate-500">Run validation to check timings, stops, terminals, distances, readings and bus conflicts.</p>}
          </Card>
        </div>
      </div>

      {editor && (
        <ActivityEditor open initial={editor} versionId={vid} activities={acts} locs={locs} routes={routes} readOnly={!canEdit}
          onClose={() => setEditor(null)} onSaved={onSaved} />
      )}

      <PublishDialog open={publishOpen} onClose={() => setPublishOpen(false)} validation={validation} lanes={busLanes} version={version}
        onPick={pickIssue} onPublished={() => { setPublishOpen(false); reloadAll(); }} />

      <Modal open={!!newVersion} title="Create a new version" onClose={() => setNewVersion(null)} onSave={async () => {
        try {
          const { data } = await client.post(`/schedules/${scheduleId}/versions`, newVersion);
          toast.ok(`Draft v${data.version_number} created from the current plan`);
          setNewVersion(null);
          await reloadSchedule();
          nav(`/schedules/${scheduleId}/v/${data.schedule_version_id}`);
        } catch (e) { toast.error(apiErrorMessage(e)); }
      }}>
        {newVersion && (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">The new draft starts as a copy of v{latest.version_number}. When published, v{latest.version_number} stays valid until the day before.</p>
            <DateInput label="Valid from" required value={newVersion.valid_from} onChange={(v) => setNewVersion({ ...newVersion, valid_from: v })} />
            <TextArea label="Reason for change" value={newVersion.change_reason} onChange={(e) => setNewVersion({ ...newVersion, change_reason: e.target.value })} />
          </div>
        )}
      </Modal>

      <Modal open={!!headerForm} title="Edit schedule header" onClose={() => setHeaderForm(null)} onSave={async () => {
        try {
          await client.put(`/schedules/${scheduleId}`, headerForm);
          toast.ok("Schedule updated");
          setHeaderForm(null);
          reloadAll(); // a new start date can move draft versions too
        } catch (e) { toast.error(apiErrorMessage(e)); }
      }}>
        {headerForm && (
          <div className="space-y-3">
            <TextInput label="Schedule name" value={headerForm.schedule_name} onChange={(e) => setHeaderForm({ ...headerForm, schedule_name: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <DateInput label="Effective from" required value={headerForm.effective_from} onChange={(v) => setHeaderForm({ ...headerForm, effective_from: v })} />
              <DateInput label="Effective to (blank = open-ended)" value={headerForm.effective_to} base={headerForm.effective_from} onChange={(v) => setHeaderForm({ ...headerForm, effective_to: v })} />
            </div>
            <p className="-mt-1 text-xs text-slate-500">Draft versions starting with the schedule move with a new start date. A later start is refused while a published version or a trip sheet falls before it; an earlier start does not make a published version start earlier.</p>
            {can("PUBLISHER") && schedule.status !== "RETIRED" && (
              <Button variant="danger" size="sm" type="button" onClick={async () => {
                if (!window.confirm("Retire this schedule? It will stop counting against the bus. History is kept.")) return;
                await client.put(`/schedules/${scheduleId}`, { status: "RETIRED" });
                setHeaderForm(null);
                reloadSchedule();
              }}>Retire schedule</Button>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}

function PublishDialog({ open, onClose, validation, lanes, version, onPick, onPublished }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setReason(version?.change_reason || ""); setAck(false); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!open) return null;
  const blocked = !validation || !validation.valid;
  const needsAck = validation?.warning_count > 0;
  const publish = async () => {
    if (blocked) return;
    if (needsAck && !ack) return toast.error("Tick the box to acknowledge the warnings");
    setBusy(true);
    try {
      await client.post(`/schedule-versions/${version.schedule_version_id}/publish`, { change_reason: reason || null, acknowledge_warnings: ack });
      toast.ok(`v${version.version_number} published`);
      onPublished();
    } catch (e) {
      toast.error(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open title={`Publish v${version.version_number}`} wide onClose={onClose} onSave={publish}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="success" icon={Send} disabled={blocked} loading={busy} onClick={publish}>Publish</Button></>}>
      <div className="space-y-4">
        <IssueList result={validation} onPick={onPick} />
        {lanes.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold text-ink">This bus over three operating days</p>
            <BusUsage lanes={lanes} />
          </div>
        )}
        {!blocked && (
          <>
            <TextArea label="Change reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            {needsAck && <Checkbox checked={ack} onChange={setAck} label={`I have reviewed the ${validation.warning_count} warning(s) and want to publish anyway`} />}
            <p className="text-xs text-slate-500">Once published this version is locked. Later changes need a new version; history is preserved.</p>
          </>
        )}
      </div>
    </Modal>
  );
}
