import { useMemo, useState } from "react";
import { INK, TYPE_COLOR } from "./colors";
import { fmtRel, label, relMin } from "../../lib/format";

/** Collect planned SOC readings in time order. A null breaks the line (never interpolated across). */
export function socPoints(activities) {
  const pts = [];
  const sorted = [...(activities || [])].sort((a, b) => a.sequence_number - b.sequence_number);
  for (const a of sorted) {
    const push = (min, v, what) => pts.push({ min, soc: v === null || v === undefined ? null : Number(v), what, a });
    if (a.trip) {
      const stops = a.trip.stops || [];
      if (stops.some((s) => s.planned_soc_pct !== null && s.planned_soc_pct !== undefined)) {
        for (const s of stops) {
          const m = relMin(s.departure_day_offset ?? s.arrival_day_offset, s.scheduled_departure_time || s.scheduled_arrival_time);
          push(m, s.planned_soc_pct, `${a.trip.trip_number} at ${s.location_name}`);
        }
      } else {
        push(a.start_min, a.trip.planned_start_soc_pct, `${a.trip.trip_number} start`);
        push(a.end_min, a.trip.planned_end_soc_pct, `${a.trip.trip_number} end`);
      }
    } else {
      const d = a.movement || a.charging || a.layover || a.halt;
      if (d) {
        push(a.start_min, d.planned_start_soc_pct, `${label(a.activity_type)} start`);
        push(a.end_min, d.planned_end_soc_pct, `${label(a.activity_type)} end`);
      }
    }
  }
  return pts.filter((p) => p.min !== null);
}

export default function SocProfile({ activities, height = 200 }) {
  const pts = useMemo(() => socPoints(activities), [activities]);
  const [hover, setHover] = useState(null);
  const known = pts.filter((p) => p.soc !== null);
  if (known.length < 2) {
    return <p className="py-6 text-center text-xs text-slate-400">Enter planned SOC on trips, movements or charging to see the state-of-charge profile. Missing readings are left blank, never estimated.</p>;
  }
  const acts = activities || [];
  const min = Math.min(...acts.map((a) => a.start_min));
  const max = Math.max(...acts.map((a) => a.end_min));
  const W = 1000, T = 10, B = 24, Lp = 34, Rp = 8;
  const x = (m) => Lp + ((m - min) / Math.max(max - min, 1)) * (W - Lp - Rp);
  const y = (v) => T + (1 - v / 100) * (height - T - B);
  // split into continuous segments
  const segs = [];
  let cur = [];
  for (const p of pts) {
    if (p.soc === null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p);
  }
  if (cur.length) segs.push(cur);
  const onMove = (e) => {
    const svg = e.currentTarget;
    const r = svg.getBoundingClientRect();
    const mx = ((e.clientX - r.left) / r.width) * W;
    let best = null;
    for (const p of known) if (!best || Math.abs(x(p.min) - mx) < Math.abs(x(best.min) - mx)) best = p;
    setHover(best);
  };
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full" onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="Planned state of charge">
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line x1={Lp} x2={W - Rp} y1={y(v)} y2={y(v)} stroke={INK.grid} />
            <text x={Lp - 6} y={y(v) + 4} textAnchor="end" fontSize="12" fill={INK.muted}>{v}%</text>
          </g>
        ))}
        {acts.filter((a) => a.activity_type === "CHARGING").map((a) => (
          <rect key={a.activity_id} x={x(a.start_min)} y={T} width={Math.max(x(a.end_min) - x(a.start_min), 1)} height={height - T - B} fill={TYPE_COLOR.CHARGING} opacity="0.1" />
        ))}
        {segs.map((s, i) => (
          <polyline key={i} fill="none" stroke={TYPE_COLOR.PASSENGER_TRIP} strokeWidth="2" strokeLinejoin="round"
            points={s.map((p) => `${x(p.min)},${y(p.soc)}`).join(" ")} />
        ))}
        {[0, 1].map((k) => {
          const m = k ? max : min;
          return <text key={k} x={x(m)} y={height - 6} textAnchor={k ? "end" : "start"} fontSize="12" fill={INK.muted}>{fmtRel(m)}</text>;
        })}
        {hover && (
          <g>
            <line x1={x(hover.min)} x2={x(hover.min)} y1={T} y2={height - B} stroke={INK.secondary} strokeDasharray="2 3" />
            <circle cx={x(hover.min)} cy={y(hover.soc)} r="4.5" fill={TYPE_COLOR.PASSENGER_TRIP} stroke="#fff" strokeWidth="2" />
          </g>
        )}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute top-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs shadow"
          style={{ left: `min(calc(${(x(hover.min) / W) * 100}% + 8px), calc(100% - 180px))` }}>
          <b className="tabular-nums">{hover.soc}%</b> · {hover.what} · <span className="tabular-nums">{fmtRel(hover.min)}</span>
        </div>
      )}
      <p className="mt-1 text-[11px] text-slate-400">Planned reference values. Shaded = charging. Breaks in the line = no reading entered. SOC may rise while driving (regenerative braking).</p>
    </div>
  );
}
