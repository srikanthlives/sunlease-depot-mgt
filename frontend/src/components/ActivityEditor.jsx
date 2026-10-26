import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Moon } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import { Button, Modal } from "./ui";
import { Combobox, Field, NumberInput, Select, TextArea, TextInput, TimeInput } from "./inputs";
import { TYPE_COLOR } from "./viz/colors";
import { fmtDuration, fmtRel, label, options, relMin } from "../lib/format";
import { gridArrows } from "../lib/grid";
import { formKeys } from "../lib/keys";
import { locOptions } from "../lib/useApi";

const PURPOSES = ["DEPOT_POSITIONING", "CHARGING_ACCESS", "RETURN_TO_SERVICE", "RETURN_TO_DEPOT", "MAINTENANCE", "OTHER"];
const PAY = ["PAYABLE", "NON_PAYABLE", "TO_BE_CONFIRMED"];
const BASIS = ["PER_KM", "FIXED_AMOUNT", "INCLUDED_IN_CONTRACT", "OTHER", "UNSPECIFIED"];
const LAYOVER = ["TERMINAL_RECOVERY", "INTER_TRIP", "OVERNIGHT_PARKING", "OTHER"];
const n = (v) => (v === null || v === undefined || v === "" ? null : Number(v));

/** Build the editor state for a new activity, continuing from the previous one. */
export function newActivity(type, prev, activities) {
  const loc = prev?.destination_location_id ?? null;
  const trips = activities.filter((a) => a.trip).map((a) => a.trip.trip_number);
  let k = trips.length + 1;
  while (trips.includes(`T${k}`)) k++;
  const base = {
    activity_type: type, origin_location_id: loc, destination_location_id: ["CHARGING", "LAYOVER", "HALT"].includes(type) ? loc : null,
    start_day_offset: prev?.end_day_offset ?? 0, scheduled_start_time: prev?.scheduled_end_time ?? null,
    end_day_offset: prev?.end_day_offset ?? 0, scheduled_end_time: null, remarks: "",
  };
  // the new event starts where the previous one ended
  const lastSoc = (prev?.trip || prev?.movement || prev?.charging || prev?.layover || prev?.halt)?.planned_end_soc_pct ?? null;
  if (type === "PASSENGER_TRIP") base.trip = { trip_number: `T${k}`, route_id: null, direction_id: null, planned_distance_km: null, stops: [], _startSoc: n(lastSoc) };
  if (type === "NON_REVENUE_MOVEMENT") base.movement = { movement_purpose: null, planned_distance_km: null, planned_start_soc_pct: n(lastSoc), planned_end_soc_pct: null, payability_status: "TO_BE_CONFIRMED", payment_basis: "UNSPECIFIED" };
  if (type === "CHARGING") base.charging = { charging_location_id: loc, planned_start_soc_pct: n(lastSoc), planned_end_soc_pct: null, expected_energy_kwh: null };
  if (type === "HALT") base.halt = { location_id: loc, planned_start_soc_pct: n(lastSoc), planned_end_soc_pct: null };
  if (type === "LAYOVER") base.layover = { location_id: loc, layover_purpose: "INTER_TRIP", planned_start_soc_pct: n(lastSoc), planned_end_soc_pct: null };
  return base;
}

/** Carry day offsets forward through a stop list: a time earlier than the previous one rolls to the next day. */
function carryOffsets(stops, startOffset) {
  let off = startOffset || 0;
  let last = null;
  return stops.map((s) => {
    const out = { ...s };
    for (const [t, o] of [["scheduled_arrival_time", "arrival_day_offset"], ["scheduled_departure_time", "departure_day_offset"]]) {
      if (!out[t]) { out[o] = null; continue; }
      const m = relMin(0, out[t]);
      if (last !== null && m < last) off += 1;
      out[o] = off;
      last = m;
    }
    return out;
  });
}

function StopTimetable({ trip, setTrip, direction, startOffset }) {
  const grid = useRef(null);
  const stops = trip.stops;
  const setStop = (i, patch) => setTrip({ ...trip, stops: carryOffsets(stops.map((s, j) => (j === i ? { ...s, ...patch } : s)), startOffset) });
  const prevTime = (i, field) => {
    if (field === "dep") return stops[i].scheduled_arrival_time;
    for (let j = i - 1; j >= 0; j--) { const t = stops[j].scheduled_departure_time || stops[j].scheduled_arrival_time; if (t) return t; }
    return null;
  };
  const first = relMin(stops[0]?.departure_day_offset, stops[0]?.scheduled_departure_time);
  const last = relMin(stops[stops.length - 1]?.arrival_day_offset, stops[stops.length - 1]?.scheduled_arrival_time);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <span className="ml-auto text-xs text-slate-500">
          {first !== null && last !== null ? <>Trip time <b className="tabular-nums text-ink">{fmtDuration(last - first)}</b> · {fmtRel(first)} → {fmtRel(last)}</> : "Enter origin departure and destination arrival"}
        </span>
      </div>
      <div ref={grid} className="overflow-x-auto rounded-lg border border-slate-200" onKeyDown={gridArrows}>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <tr><th className="px-2 py-1.5">#</th><th className="px-2 py-1.5">Stop</th><th className="px-2 py-1.5 text-right">km</th>
              <th className="px-2 py-1.5">Arrival</th><th className="px-2 py-1.5">Departure</th><th className="px-2 py-1.5">Dwell</th>
              <th className="px-2 py-1.5 text-right">SOC %</th></tr>
          </thead>
          <tbody>
            {stops.map((s, i) => {
              const isFirst = i === 0, isLast = i === stops.length - 1;
              const arr = relMin(s.arrival_day_offset, s.scheduled_arrival_time), dep = relMin(s.departure_day_offset, s.scheduled_departure_time);
              const crossed = i > 0 && (s.arrival_day_offset ?? s.departure_day_offset ?? 0) > (stops[i - 1].departure_day_offset ?? stops[i - 1].arrival_day_offset ?? 0);
              return (
                <tr key={s.route_stop_id} className="border-t border-slate-100">
                  <td className="px-2 py-1 text-xs text-slate-400">{i + 1}</td>
                  <td className="px-2 py-1"><span className="font-medium">{s.location_name}</span>
                    {crossed && <span className="ml-1 inline-flex items-center gap-0.5 text-[11px] text-brand-700"><Moon className="h-3 w-3" />next day</span>}</td>
                  <td className="px-2 py-1 text-right text-xs tabular-nums text-slate-500">{Number(s.cumulative_km)}</td>
                  <td className="px-2 py-1" data-row={i} data-col="arr">
                    {isFirst ? <span className="text-xs text-slate-400">—</span> : (
                      <div className="flex items-center gap-1">
                        <TimeInput value={s.scheduled_arrival_time} placeholder={prevTime(i, "arr") || "HH:MM"} suggest={prevTime(i, "arr")} onChange={(v) => setStop(i, { scheduled_arrival_time: v, ...(isLast ? {} : !s.scheduled_departure_time && v ? { scheduled_departure_time: v } : {}) })} />
                        {s.arrival_day_offset > 0 && <span className="rounded bg-brand-50 px-1 text-[11px] font-semibold text-brand-700">+{s.arrival_day_offset}</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1" data-row={i} data-col="dep">
                    {isLast ? <span className="text-xs text-slate-400">—</span> : (
                      <div className="flex items-center gap-1">
                        <TimeInput value={s.scheduled_departure_time} placeholder={prevTime(i, "dep") || "HH:MM"} suggest={prevTime(i, "dep")} onChange={(v) => setStop(i, { scheduled_departure_time: v })} />
                        {s.departure_day_offset > 0 && <span className="rounded bg-brand-50 px-1 text-[11px] font-semibold text-brand-700">+{s.departure_day_offset}</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1 text-xs tabular-nums text-slate-500">{arr !== null && dep !== null ? (dep < arr ? <span className="text-danger">negative</span> : fmtDuration(dep - arr)) : ""}</td>
                  <td className="px-2 py-1" data-row={i} data-col="soc"><NumberInput min={0} max={100} value={s.planned_soc_pct} onChange={(v) => setStop(i, { planned_soc_pct: v })} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-500">
        Stops load from the {direction?.direction_code} direction. Press Enter on an empty time to take the greyed suggestion (previous departure); a departure defaults to its arrival.
        A time earlier than the previous one rolls to the next day automatically (+1). The km column is the route distance from the origin; SOC is an optional planning reference.
      </p>
    </div>
  );
}

export default function ActivityEditor({ open, initial, versionId, activities, locs, routes, onClose, onSaved, readOnly }) {
  const toast = useToast();
  const [a, setA] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  useEffect(() => { setA(initial); setErrors({}); }, [initial]);
  useEffect(() => { setErrors((e) => (Object.keys(e).length ? {} : e)); }, [a]);
  const saveRef = useRef(null);
  const allLocs = useMemo(() => locOptions(locs), [locs]);
  const chargers = useMemo(() => locOptions(locs, (l) => l.supports_charging), [locs]);
  const routeOpts = (routes || []).filter((r) => r.status === "ACTIVE").map((r) => ({ value: r.route_id, label: r.route_name, sub: r.route_code }));
  if (!a) return null;
  const type = a.activity_type;
  const route = (routes || []).find((r) => r.route_id === a.trip?.route_id);
  const direction = route?.directions.find((d) => d.direction_id === a.trip?.direction_id);
  const set = (patch) => setA((x) => ({ ...x, ...patch }));
  const setDetail = (key, patch) => setA((x) => ({ ...x, [key]: { ...x[key], ...patch } }));

  // trip start/end come from the stop timetable
  const tripStart = a.trip?.stops?.[0];
  const tripEnd = a.trip?.stops?.[a.trip.stops.length - 1];
  const startMin = type === "PASSENGER_TRIP" ? relMin(tripStart?.departure_day_offset, tripStart?.scheduled_departure_time) : relMin(a.start_day_offset, a.scheduled_start_time);
  const endMin = type === "PASSENGER_TRIP" ? relMin(tripEnd?.arrival_day_offset, tripEnd?.scheduled_arrival_time) : relMin(a.end_day_offset, a.scheduled_end_time);
  const duration = startMin !== null && endMin !== null ? endMin - startMin : null;
  const suggestNextDay = type !== "PASSENGER_TRIP" && duration !== null && duration <= 0 && a.end_day_offset <= a.start_day_offset;

  const pickDirection = (dirId) => {
    const d = route?.directions.find((x) => x.direction_id === Number(dirId));
    if (!d) return setDetail("trip", { direction_id: null, stops: [] });
    const startOff = a.start_day_offset || 0;
    const stops = d.stops.map((s, i) => ({
      route_stop_id: s.route_stop_id, stop_sequence: s.stop_sequence, location_code: s.location_code, location_name: s.location_name,
      cumulative_km: Number(s.cumulative_distance_km),
      scheduled_arrival_time: null, arrival_day_offset: null,
      scheduled_departure_time: i === 0 ? a.scheduled_start_time : null, departure_day_offset: i === 0 ? startOff : null,
      planned_soc_pct: i === 0 ? a.trip._startSoc ?? null : null,
    }));
    setA((x) => ({ ...x, origin_location_id: d.start_terminal_id, destination_location_id: d.end_terminal_id,
      trip: { ...x.trip, direction_id: d.direction_id, planned_distance_km: x.trip.planned_distance_km ?? Number(d.total_distance_km), stops: carryOffsets(stops, startOff) } }));
  };

  const payload = () => {
    const body = {
      activity_type: type, origin_location_id: a.origin_location_id, destination_location_id: a.destination_location_id,
      start_day_offset: a.start_day_offset || 0, scheduled_start_time: a.scheduled_start_time, end_day_offset: a.end_day_offset || 0,
      scheduled_end_time: a.scheduled_end_time, remarks: a.remarks || null,
    };
    if (a.sequence_number) body.sequence_number = a.sequence_number;
    if (type === "PASSENGER_TRIP") {
      const t = a.trip;
      const st = t.stops;
      body.start_day_offset = st[0]?.departure_day_offset ?? 0;
      body.scheduled_start_time = st[0]?.scheduled_departure_time;
      body.end_day_offset = st[st.length - 1]?.arrival_day_offset ?? 0;
      body.scheduled_end_time = st[st.length - 1]?.scheduled_arrival_time;
      body.trip = {
        trip_number: t.trip_number, route_id: t.route_id, direction_id: t.direction_id, planned_distance_km: t.planned_distance_km,
        planned_start_soc_pct: n(st[0]?.planned_soc_pct), planned_end_soc_pct: n(st[st.length - 1]?.planned_soc_pct),
        stops: st.filter((s) => s.scheduled_arrival_time || s.scheduled_departure_time || n(s.planned_soc_pct) !== null).map((s) => ({
          route_stop_id: s.route_stop_id, stop_sequence: s.stop_sequence,
          arrival_day_offset: s.scheduled_arrival_time ? s.arrival_day_offset : null, scheduled_arrival_time: s.scheduled_arrival_time || null,
          departure_day_offset: s.scheduled_departure_time ? s.departure_day_offset : null, scheduled_departure_time: s.scheduled_departure_time || null,
          planned_soc_pct: n(s.planned_soc_pct),
        })),
      };
    }
    if (type === "NON_REVENUE_MOVEMENT") body.movement = { ...a.movement };
    if (type === "CHARGING") body.charging = { ...a.charging, charging_location_id: a.origin_location_id };
    if (type === "HALT") body.halt = { ...a.halt, location_id: a.origin_location_id };
    if (type === "LAYOVER") body.layover = { ...a.layover, location_id: a.origin_location_id };
    return body;
  };

  const check = (b) => {
    const e = {};
    if (!b.origin_location_id) e.origin = "Required";
    if (!b.destination_location_id) e.destination = "Required";
    if (!b.scheduled_start_time) e.start = type === "PASSENGER_TRIP" ? "Enter the origin departure time" : "Required";
    if (!b.scheduled_end_time) e.end = type === "PASSENGER_TRIP" ? "Enter the destination arrival time" : "Required";
    if (b.scheduled_start_time && b.scheduled_end_time && duration !== null && duration <= 0) e.end = "End must be after start - check the day offset";
    if (type === "PASSENGER_TRIP") {
      if (!b.trip.trip_number) e.trip_number = "Required";
      if (!b.trip.route_id) e.route = "Required";
      if (!b.trip.direction_id) e.direction = "Required";
      if (!(b.trip.planned_distance_km > 0)) e.distance = "Required";
    }
    if (type === "NON_REVENUE_MOVEMENT") {
      if (!b.movement.movement_purpose) e.purpose = "Required";
      if (b.movement.planned_distance_km === null) e.distance = "Required (0 is allowed)";
    }
    return e;
  };

  const save = async (andNext = false) => {
    if (readOnly) return onClose();
    const b = payload();
    const e = check(b);
    setErrors(e);
    if (Object.keys(e).length) {
      toast.error(Object.values(e)[0]);
      return;
    }
    setSaving(true);
    try {
      const r = a.activity_id ? await client.put(`/activities/${a.activity_id}`, b) : await client.post(`/schedule-versions/${versionId}/activities`, b);
      toast.ok(`#${r.data.sequence_number} ${label(type)} saved`);
      onSaved(r.data, andNext && !a.activity_id);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  saveRef.current = save;
  const routeDist = Number(direction?.total_distance_km || 0);
  const planned = Number(a.trip?.planned_distance_km || 0);
  const diffPct = routeDist ? (Math.abs(planned - routeDist) / routeDist) * 100 : 0;
  const title = (
    <span className="flex items-center gap-2">
      <span className="h-3 w-3 rounded-sm" style={{ background: TYPE_COLOR[type] }} />
      {a.activity_id ? `#${a.sequence_number} ` : "Add "}{label(type)}{readOnly ? " (read-only)" : ""}
    </span>
  );
  const stationary = type === "CHARGING" || type === "LAYOVER" || type === "HALT";
  return (
    <Modal open={open} title={title} onClose={onClose} onSave={() => save(false)} xwide={type === "PASSENGER_TRIP"} wide={type !== "PASSENGER_TRIP"}
      footer={readOnly ? <Button onClick={onClose}>Close</Button> : (
        <>
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          {!a.activity_id && <Button variant="secondary" type="button" loading={saving} onClick={() => save(true)} title="Save, then start the next activity">Save & add next</Button>}
          <Button type="button" loading={saving} onClick={() => save(false)}>Save</Button>
        </>
      )}>
      <fieldset disabled={readOnly} className="space-y-4" onKeyDown={(e) => { if (e.key === "Enter" && e.altKey) { e.preventDefault(); document.activeElement?.blur(); setTimeout(() => saveRef.current(true), 0); } }}>
        {/* when / where */}
        <div className="grid gap-3 sm:grid-cols-4">
          {type === "PASSENGER_TRIP" ? (
            <>
              <TextInput label="Trip number" required value={a.trip.trip_number} error={errors.trip_number} onChange={(e) => setDetail("trip", { trip_number: e.target.value.toUpperCase() })} />
              <Combobox label="Route" required options={routeOpts} value={a.trip.route_id} error={errors.route}
                onChange={(v) => setA((x) => ({ ...x, trip: { ...x.trip, route_id: v, direction_id: null, stops: [], planned_distance_km: null } }))} />
              <Select label="Direction" required placeholder={route ? "Select direction" : "Pick a route first"} error={errors.direction}
                options={(route?.directions || []).filter((d) => d.is_active && d.stops.length >= 2).map((d) => ({ value: d.direction_id, label: `${d.direction_code} · ${d.start_terminal_name} → ${d.end_terminal_name}` }))}
                value={a.trip.direction_id ?? ""} onChange={pickDirection} />
              <NumberInput label="Planned distance" required suffix="km" min={0.01} value={a.trip.planned_distance_km} error={errors.distance} onChange={(v) => setDetail("trip", { planned_distance_km: v })} />
            </>
          ) : stationary ? (
            <Combobox label={type === "CHARGING" ? "Charging location" : type === "HALT" ? "Halt location (depot or terminal)" : "Layover location"} required className="sm:col-span-2"
              options={type === "CHARGING" ? chargers : allLocs} value={a.origin_location_id} error={errors.origin}
              onChange={(v) => set({ origin_location_id: v, destination_location_id: v })} />
          ) : (
            <>
              <Combobox label="From" required options={allLocs} value={a.origin_location_id} error={errors.origin} onChange={(v) => set({ origin_location_id: v })} />
              <Combobox label="To" required options={allLocs} value={a.destination_location_id} error={errors.destination} onChange={(v) => set({ destination_location_id: v })} />
            </>
          )}
          {type !== "PASSENGER_TRIP" && (
            <>
              <TimeInput label="Start (day offset)" required value={a.scheduled_start_time} offset={a.start_day_offset} error={errors.start}
                onChange={(v) => set({ scheduled_start_time: v })} onOffsetChange={(v) => set({ start_day_offset: v, end_day_offset: Math.max(v, a.end_day_offset) })} />
              <TimeInput label="End (day offset)" required value={a.scheduled_end_time} offset={a.end_day_offset} error={errors.end}
                onChange={(v) => set({ scheduled_end_time: v })} onOffsetChange={(v) => set({ end_day_offset: v })} />
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs">
          <span className="text-slate-500">Duration</span>
          <b className={`tabular-nums ${duration !== null && duration <= 0 ? "text-danger" : "text-ink"}`}>{duration === null ? "—" : fmtDuration(duration)}</b>
          {startMin !== null && endMin !== null && <span className="tabular-nums text-slate-500">{fmtRel(startMin)} → {fmtRel(endMin)}</span>}
          {startMin !== null && endMin !== null && Math.floor(endMin / 1440) > Math.floor(startMin / 1440) && <span className="inline-flex items-center gap-1 text-brand-700"><Moon className="h-3.5 w-3.5" /> crosses midnight</span>}
          {suggestNextDay && a.scheduled_end_time && (
            <span className="inline-flex items-center gap-2 text-[#8a5a00]">
              <AlertTriangle className="h-3.5 w-3.5" /> End is not after start. Does it finish the next day?
              <Button size="sm" variant="secondary" type="button" onClick={() => set({ end_day_offset: a.start_day_offset + 1 })}>Set end to +{a.start_day_offset + 1}</Button>
            </span>
          )}
          {type === "PASSENGER_TRIP" && direction && (
            diffPct <= 2 ? <span className="ml-auto inline-flex items-center gap-1 text-[#0a6e0a]"><CheckCircle2 className="h-3.5 w-3.5" /> matches route distance {routeDist} km</span>
              : <span className="ml-auto inline-flex items-center gap-1 text-[#8a5a00]"><AlertTriangle className="h-3.5 w-3.5" /> route is {routeDist} km ({diffPct.toFixed(1)}% difference)</span>
          )}
        </div>

        {type === "PASSENGER_TRIP" && (direction ? (
          <StopTimetable trip={a.trip} setTrip={(t) => setA((x) => ({ ...x, trip: t }))} direction={direction} startOffset={a.start_day_offset} />
        ) : <p className="rounded-lg border border-dashed border-slate-300 py-6 text-center text-xs text-slate-400">Pick a route and direction - its stops load here automatically</p>)}

        {type === "NON_REVENUE_MOVEMENT" && (
          <div className="grid gap-3 sm:grid-cols-4">
            <Select label="Purpose" required placeholder="Select" options={options(PURPOSES)} value={a.movement.movement_purpose} error={errors.purpose} onChange={(v) => setDetail("movement", { movement_purpose: v })} />
            <Select label="Payability" required options={options(PAY)} value={a.movement.payability_status} onChange={(v) => setDetail("movement", { payability_status: v })} />
            <Select label="Payment basis" options={options(BASIS)} value={a.movement.payment_basis} onChange={(v) => setDetail("movement", { payment_basis: v })} />
            <NumberInput label="Distance" required suffix="km" min={0} value={a.movement.planned_distance_km} error={errors.distance}
              onChange={(v) => setDetail("movement", { planned_distance_km: v })} />
            <NumberInput label="Start SOC" suffix="%" min={0} max={100} value={a.movement.planned_start_soc_pct} onChange={(v) => setDetail("movement", { planned_start_soc_pct: v })} />
            <NumberInput label="End SOC" suffix="%" min={0} max={100} value={a.movement.planned_end_soc_pct} onChange={(v) => setDetail("movement", { planned_end_soc_pct: v })} />
            <p className="text-xs text-slate-500 sm:col-span-4">Purpose and payability are independent: a movement to a charger can still be payable.</p>
          </div>
        )}
        {type === "CHARGING" && (
          <div className="grid gap-3 sm:grid-cols-3">
            <NumberInput label="Start SOC" suffix="%" min={0} max={100} value={a.charging.planned_start_soc_pct} onChange={(v) => setDetail("charging", { planned_start_soc_pct: v })} />
            <NumberInput label="End SOC" suffix="%" min={0} max={100} value={a.charging.planned_end_soc_pct} onChange={(v) => setDetail("charging", { planned_end_soc_pct: v })} />
            <NumberInput label="Expected energy" suffix="kWh" min={0} value={a.charging.expected_energy_kwh} onChange={(v) => setDetail("charging", { expected_energy_kwh: v })} />
            <p className="text-xs text-slate-500 sm:col-span-3">Charging is stationary. Add the drive to and from the charger as separate movements.</p>
          </div>
        )}
        {type === "HALT" && (
          <div className="grid gap-3 sm:grid-cols-3">
            <NumberInput label="Start SOC" suffix="%" min={0} max={100} value={a.halt.planned_start_soc_pct} onChange={(v) => setDetail("halt", { planned_start_soc_pct: v })} />
            <NumberInput label="End SOC" suffix="%" min={0} max={100} value={a.halt.planned_end_soc_pct} onChange={(v) => setDetail("halt", { planned_end_soc_pct: v })} />
            <p className="text-xs text-slate-500 sm:col-span-3">One off-service block at the depot or a night-halt terminal. Washing, charging and maintenance can happen inside it without separate times, so SOC may go up or down. Halt time is not counted in the cycle time.</p>
          </div>
        )}
        {type === "LAYOVER" && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Select label="Purpose" options={options(LAYOVER)} value={a.layover.layover_purpose} onChange={(v) => setDetail("layover", { layover_purpose: v })} />
            <NumberInput label="Start SOC" suffix="%" min={0} max={100} value={a.layover.planned_start_soc_pct} onChange={(v) => setDetail("layover", { planned_start_soc_pct: v })} />
            <NumberInput label="End SOC" suffix="%" min={0} max={100} value={a.layover.planned_end_soc_pct} onChange={(v) => setDetail("layover", { planned_end_soc_pct: v })} />
            <p className="text-xs text-slate-500 sm:col-span-3">The bus stays powered during a layover (A/C on), so SOC can drop depending on how long it waits.</p>
          </div>
        )}
        <TextArea label="Remarks" value={a.remarks || ""} onChange={(e) => set({ remarks: e.target.value })} />
        {!readOnly && <p className="text-[11px] text-slate-400">Alt+Enter: save & add next</p>}
      </fieldset>
    </Modal>
  );
}

/** Convert an activity from the version-detail API into editor state. */
export function toEditor(act, routes) {
  const a = JSON.parse(JSON.stringify(act));
  if (a.trip) {
    const route = (routes || []).find((r) => r.route_id === a.trip.route_id);
    const dir = route?.directions.find((d) => d.direction_id === a.trip.direction_id);
    const saved = Object.fromEntries(a.trip.stops.map((s) => [s.route_stop_id, s]));
    a.trip.planned_distance_km = Number(a.trip.planned_distance_km);
    a.trip.stops = (dir?.stops || []).map((rs) => {
      const s = saved[rs.route_stop_id] || {};
      return {
        route_stop_id: rs.route_stop_id, stop_sequence: rs.stop_sequence, location_code: rs.location_code, location_name: rs.location_name,
        cumulative_km: Number(rs.cumulative_distance_km),
        scheduled_arrival_time: s.scheduled_arrival_time || null, arrival_day_offset: s.arrival_day_offset ?? null,
        scheduled_departure_time: s.scheduled_departure_time || null, departure_day_offset: s.departure_day_offset ?? null,
        planned_soc_pct: n(s.planned_soc_pct),
      };
    });
  }
  for (const k of ["movement", "charging", "layover", "halt"]) {
    if (a[k]) for (const f of Object.keys(a[k])) if (/km|pct|kwh/.test(f)) a[k][f] = n(a[k][f]);
  }
  return a;
}
