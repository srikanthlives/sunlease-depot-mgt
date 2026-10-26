import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Eye, Moon, Printer } from "lucide-react";
import client from "../api/client";
import { Badge, Button, Card, Empty, PageHeader, Spinner } from "../components/ui";
import { Combobox, DateInput, Select, TextInput } from "../components/inputs";
import ScheduleGantt from "../components/viz/ScheduleGantt";
import { TYPE_COLOR } from "../components/viz/colors";
import { fmtDate, fmtDateLong, fmtDuration, label, options, todayIso } from "../lib/format";
import { locOptions, useApi } from "../lib/useApi";

const TYPES = ["PASSENGER_TRIP", "NON_REVENUE_MOVEMENT", "CHARGING", "LAYOVER", "HALT"];

function detail(a) {
  if (a.trip) return `${a.trip.trip_number} · ${a.trip.route_code} ${a.trip.direction_code}`;
  if (a.movement) return `${label(a.movement.movement_purpose)} · ${label(a.movement.payability_status)}`;
  if (a.charging) return a.charging.start_soc !== null ? `SOC ${a.charging.start_soc}% → ${a.charging.end_soc ?? "?"}%` : "";
  if (a.halt) return `Off service${a.halt.start_soc !== null ? ` · SOC ${a.halt.start_soc}% → ${a.halt.end_soc ?? "?"}%` : ""}`;
  if (a.layover) return `${label(a.layover.layover_purpose)}${a.layover.start_soc !== null ? ` · SOC ${a.layover.start_soc}% → ${a.layover.end_soc ?? "?"}%` : ""}`;
  return "";
}

export default function ScheduleViewer() {
  const { data: locs = [] } = useApi("/locations", []);
  const { data: vehicles = [] } = useApi("/vehicles", []);
  const [f, setF] = useState({ date: todayIso(), depot_id: null, vehicle_id: null, code: "", activity_type: null, status: "PUBLISHED" });
  const [items, setItems] = useState(null);
  const [expanded, setExpanded] = useState({});
  useEffect(() => {
    let live = true;
    (async () => {
      setItems(null);
      const p = new URLSearchParams();
      if (f.date) p.set("on_date", f.date);
      if (f.depot_id) p.set("depot_id", f.depot_id);
      if (f.vehicle_id) p.set("vehicle_id", f.vehicle_id);
      if (f.code) p.set("code", f.code);
      if (f.status) p.set("status", f.status);
      const { data } = await client.get(`/schedules?${p}`);
      const out = [];
      for (const s of data) {
        try {
          const { data: tl } = await client.get(`/schedules/${s.schedule_id}/timeline?date=${f.date}`);
          out.push(tl);
        } catch { /* no version applies on this date */ }
      }
      if (live) setItems(out);
    })();
    return () => { live = false; };
  }, [f.date, f.depot_id, f.vehicle_id, f.code, f.status]);
  const shown = useMemo(() => (items || []).map((t) => ({ ...t, rows: t.activities.filter((a) => !f.activity_type || a.activity_type === f.activity_type) }))
    .filter((t) => !f.activity_type || t.rows.length), [items, f.activity_type]);
  const depots = locOptions(locs, (l) => l.location_type === "DEPOT");
  const buses = (vehicles || []).map((v) => ({ value: v.vehicle_id, label: v.fleet_number, sub: v.registration_number }));
  const totals = shown.reduce((acc, t) => ({ km: acc.km + t.summary.total_km, trips: acc.trips + t.summary.trip_count }), { km: 0, trips: 0 });
  return (
    <>
      <PageHeader title="Schedule viewer" subtitle={`Read-only plan for ${fmtDateLong(f.date)} - dates come from the operating date plus each activity's day offset`} />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <DateInput label="Operating date" value={f.date} onChange={(v) => setF({ ...f, date: v || todayIso() })} />
          <Combobox label="Depot" options={[{ value: "", label: "All depots" }, ...depots]} value={f.depot_id ?? ""} onChange={(v) => setF({ ...f, depot_id: v || null })} />
          <Combobox label="Bus" options={[{ value: "", label: "All buses" }, ...buses]} value={f.vehicle_id ?? ""} onChange={(v) => setF({ ...f, vehicle_id: v || null })} />
          <TextInput label="Schedule code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
          <Select label="Activity type" placeholder="All types" options={options(TYPES)} value={f.activity_type} onChange={(v) => setF({ ...f, activity_type: v })} />
          <Select label="Schedule status" placeholder="Any" options={options(["PUBLISHED", "RETIRED"])} value={f.status} onChange={(v) => setF({ ...f, status: v })} />
        </div>
      </Card>
      {items === null ? <Spinner /> : shown.length === 0 ? (
        <Card><Empty icon={Eye} title={`No published schedule operates on ${fmtDate(f.date)} for these filters`} /></Card>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-slate-600"><b>{shown.length}</b> bus{shown.length > 1 ? "es" : ""} in service · <b>{totals.trips}</b> trips · <b>{totals.km.toLocaleString("en-IN", { maximumFractionDigits: 1 })}</b> planned km</p>
          {shown.map((t) => (
            <Card key={t.schedule_id}
              title={<div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold">{t.vehicle.fleet_number}</h2>
                <Link className="text-sm text-brand-600 hover:underline" to={`/schedules/${t.schedule_id}/v/${t.schedule_version_id}`}>{t.schedule_code} v{t.version_number}</Link>
                <Badge value={t.version_status} /><span className="text-xs text-slate-500">{t.schedule_name}</span></div>}
              actions={<>
                <Button size="sm" variant="ghost" onClick={() => setExpanded({ ...expanded, [t.schedule_id]: !expanded[t.schedule_id] })}>{expanded[t.schedule_id] ? "Hide" : "Show"} timetable</Button>
                <Button size="sm" variant="secondary" icon={Printer} onClick={() => window.open(`/print/${t.schedule_version_id}?date=${f.date}`, "_blank")}>Print</Button>
              </>}>
              <ScheduleGantt compact activities={t.activities.map((a) => ({ ...a, origin_name: a.origin.name, destination_name: a.destination.name }))} operatingDate={f.date} />
              {expanded[t.schedule_id] && (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-500">
                      <th className="px-2 py-1.5">#</th><th className="px-2 py-1.5">Activity</th><th className="px-2 py-1.5">From → To</th>
                      <th className="px-2 py-1.5">Start</th><th className="px-2 py-1.5">End</th><th className="px-2 py-1.5 text-right">Duration</th><th className="px-2 py-1.5 text-right">km</th><th className="px-2 py-1.5">Details</th></tr></thead>
                    <tbody>
                      {t.rows.map((a) => (
                        <tr key={a.activity_id} className="border-b border-slate-100">
                          <td className="px-2 py-1.5 tabular-nums text-slate-500">{a.sequence_number}</td>
                          <td className="px-2 py-1.5"><span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: TYPE_COLOR[a.activity_type] }} />{label(a.activity_type)}</span></td>
                          <td className="px-2 py-1.5">{a.origin.name}{a.origin.code !== a.destination.code && ` → ${a.destination.name}`}</td>
                          <td className="px-2 py-1.5 tabular-nums whitespace-nowrap">{fmtDate(a.start_date)} {a.start_time}</td>
                          <td className="px-2 py-1.5 tabular-nums whitespace-nowrap">{fmtDate(a.end_date)} {a.end_time} {a.end_date !== a.start_date && <Moon className="inline h-3.5 w-3.5 text-brand-600" />}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{fmtDuration(a.duration_minutes)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{a.distance_km || ""}</td>
                          <td className="px-2 py-1.5 text-xs text-slate-600">{detail(a)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
