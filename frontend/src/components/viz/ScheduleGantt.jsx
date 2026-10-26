import { useMemo, useState } from "react";
import { AlertOctagon, AlertTriangle } from "lucide-react";
import { useTooltip } from "./Tooltip";
import { INK, STATUS, TYPE_COLOR, TYPE_SHORT } from "./colors";
import { addDays, fmtDate, fmtDuration, fmtRel, label } from "../../lib/format";

/**
 * Gantt-style timeline of one operating cycle.
 * activities: [{activity_id, sequence_number, activity_type, start_min, end_min, origin_name, destination_name, trip?, movement?}]
 * Overlapping activities drop into a second lane with a red hatch; gaps over `gapWarn` minutes get a dashed amber marker.
 */
const HIDDEN_KEY = "depot_gantt_hidden";
// legend groups that can be shown or hidden; payable movements toggle apart from the other movements
const GROUPS = [...Object.keys(TYPE_SHORT), "PAYABLE"];
const groupOf = (a) => (a.activity_type === "NON_REVENUE_MOVEMENT" && a.movement?.payability_status === "PAYABLE" ? "PAYABLE" : a.activity_type);
function storedHidden() {
  try { return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || "[]")); } catch { return new Set(); }
}

export default function ScheduleGantt({ activities, operatingDate, gapWarn = 30, onSelect, selectedId, compact }) {
  const tt = useTooltip();
  const [hidden, setHidden] = useState(storedHidden);
  const toggle = (g) => setHidden((h) => {
    const next = new Set(h);
    if (next.has(g)) next.delete(g); else next.add(g);
    try { localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next])); } catch { /* private mode */ }
    return next;
  });
  const acts = useMemo(() => [...(activities || [])].filter((a) => a.end_min !== null).sort((a, b) => a.sequence_number - b.sequence_number), [activities]);
  if (!acts.length) {
    return <div className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-xs text-slate-400">The timeline appears as activities are added</div>;
  }
  const min = Math.floor(Math.min(...acts.map((a) => a.start_min)) / 60) * 60;
  const max = Math.ceil(Math.max(...acts.map((a) => Math.max(a.end_min, a.start_min + 1))) / 60) * 60;
  const span = Math.max(max - min, 60);
  const W = 1000;
  const L = 8;
  const R = 8;
  const x = (m) => L + ((m - min) / span) * (W - L - R);
  const laneH = compact ? 26 : 34;
  const top = 26;

  // lane assignment: overlap with previous end -> lane 1
  const placed = [];
  const overlaps = [];
  const gaps = [];
  let prevEnd = null;
  let prev = null;
  for (const a of acts) {
    let lane = 0;
    if (prevEnd !== null && a.start_min < prevEnd) {
      lane = 1;
      overlaps.push({ from: a.start_min, to: Math.min(prevEnd, a.end_min), a, prev });
    } else if (prevEnd !== null && a.start_min - prevEnd > gapWarn) {
      gaps.push({ from: prevEnd, to: a.start_min, a });
    }
    placed.push({ ...a, lane });
    if (prevEnd === null || a.end_min > prevEnd) { prevEnd = a.end_min; prev = a; }
  }
  const lanes = overlaps.length ? 2 : 1;
  const H = top + lanes * (laneH + 6) + 22;
  const hourStep = span > 18 * 60 ? 3 : span > 8 * 60 ? 2 : 1;
  const ticks = [];
  for (let m = min; m <= max; m += 60 * hourStep) ticks.push(m);
  const midnights = [];
  for (let d = Math.ceil(min / 1440) * 1440; d <= max; d += 1440) if (d > min) midnights.push(d);

  const tipFor = (a) => (
    <div className="space-y-0.5">
      <p className="font-semibold">#{a.sequence_number} {label(a.activity_type)}{a.trip ? ` ${a.trip.trip_number}` : ""}</p>
      <p>{a.origin_name} → {a.destination_name}</p>
      <p className="tabular-nums">{fmtRel(a.start_min)} – {fmtRel(a.end_min)} · {fmtDuration(a.end_min - a.start_min)}</p>
      {a.trip && <p>{a.trip.route_code} {a.trip.direction_code} · {Number(a.trip.planned_distance_km)} km</p>}
      {a.movement && <p>{label(a.movement.movement_purpose)} · {label(a.movement.payability_status)} · {Number(a.movement.planned_distance_km)} km</p>}
    </div>
  );

  return (
    <div className="relative" data-tip-host>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        {GROUPS.map((k) => {
          const off = hidden.has(k);
          const count = acts.filter((a) => groupOf(a) === k).length;
          return (
            <button key={k} type="button" tabIndex={-1} onClick={() => toggle(k)} aria-pressed={!off} title={off ? "Show on the chart" : "Hide from the chart"}
              className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 ring-1 transition print:hidden ${off ? "text-slate-400 ring-slate-200 line-through" : "ring-slate-300 hover:bg-slate-50"}`}>
              {k === "PAYABLE"
                ? <span className={`flex h-2.5 w-3 items-center justify-end rounded-sm pr-px ${off ? "bg-slate-300" : "bg-move"}`}><span className="h-1.5 w-1.5 rounded-full bg-white" /></span>
                : <span className="h-2.5 w-2.5 rounded-sm" style={{ background: off ? "#cbd5e1" : TYPE_COLOR[k] }} />}
              {k === "PAYABLE" ? "Payable movement" : k === "NON_REVENUE_MOVEMENT" ? "Movement" : TYPE_SHORT[k]}
              <span className="tabular-nums text-slate-400">{count}</span>
            </button>
          );
        })}
        {hidden.size > 0 && <button type="button" tabIndex={-1} className="text-brand-600 hover:underline print:hidden" onClick={() => { setHidden(new Set()); try { localStorage.removeItem(HIDDEN_KEY); } catch { /* ignore */ } }}>Show all</button>}
        {overlaps.length > 0 && <span className="flex items-center gap-1 font-medium text-danger"><AlertOctagon className="h-3.5 w-3.5" /> {overlaps.length} overlap{overlaps.length > 1 ? "s" : ""}</span>}
        {gaps.length > 0 && <span className="flex items-center gap-1 font-medium text-[#8a5a00]"><AlertTriangle className="h-3.5 w-3.5" /> {gaps.length} gap{gaps.length > 1 ? "s" : ""} &gt; {gapWarn}m</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Schedule timeline">
        <defs>
          <pattern id="hatch-red" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill={STATUS.critical} opacity="0.15" />
            <line x1="0" y1="0" x2="0" y2="6" stroke={STATUS.critical} strokeWidth="2" />
          </pattern>
        </defs>
        {ticks.map((m) => (
          <g key={m}>
            <line x1={x(m)} x2={x(m)} y1={top - 4} y2={H - 20} stroke={INK.grid} strokeWidth="1" />
            <text x={x(m)} y={H - 6} textAnchor={m === min ? "start" : m + 60 * hourStep > max ? "end" : "middle"} fontSize="11" fill={INK.muted} className="tabular-nums">{fmtRel(m).replace(/ \+\d/, "")}</text>
          </g>
        ))}
        {midnights.map((m) => (
          <g key={`mn${m}`}>
            <line x1={x(m)} x2={x(m)} y1={4} y2={H - 20} stroke={INK.primary} strokeWidth="1.5" strokeDasharray="3 3" />
            <text x={x(m) + 4} y={14} fontSize="11" fontWeight="600" fill={INK.primary}>
              Day {m / 1440 + 1}{operatingDate ? ` · ${fmtDate(addDays(operatingDate, m / 1440))}` : ""}
            </text>
          </g>
        ))}
        {min < 0 || !operatingDate ? null : (
          <text x={L} y={14} fontSize="11" fontWeight="600" fill={INK.secondary}>Day 1 · {fmtDate(operatingDate)}</text>
        )}
        {gaps.map((g, i) => (
          <rect key={`gap${i}`} x={x(g.from)} y={top} width={Math.max(x(g.to) - x(g.from), 2)} height={laneH} rx="4"
            fill={STATUS.warning} fillOpacity="0.08" stroke={STATUS.warning} strokeDasharray="4 3" strokeWidth="1.5"
            onMouseMove={(e) => tt.show(e, <p><b>Unexplained gap</b> of {fmtDuration(g.to - g.from)} before #{g.a.sequence_number}</p>)} onMouseLeave={tt.hide} />
        ))}
        {placed.filter((a) => !hidden.has(groupOf(a))).map((a) => {
          const x0 = x(a.start_min);
          const w = Math.max(x(a.end_min) - x0 - 2, 2);
          const y0 = top + a.lane * (laneH + 6);
          const sel = selectedId === a.activity_id;
          const text = a.trip ? a.trip.trip_number : a.activity_type === "CHARGING" ? "⚡" : a.activity_type === "LAYOVER" ? "" : "";
          return (
            <g key={a.activity_id} className={onSelect ? "cursor-pointer" : undefined} onClick={() => onSelect?.(a.activity_id)}
              onMouseMove={(e) => tt.show(e, tipFor(a))} onMouseLeave={tt.hide}>
              <rect x={x0 + 1} y={y0} width={w} height={laneH} rx="4" fill={TYPE_COLOR[a.activity_type]}
                stroke={sel ? INK.primary : "#fff"} strokeWidth={sel ? 2.5 : 1} opacity={a.activity_type === "LAYOVER" ? 0.85 : 1} />
              {a.movement?.payability_status === "PAYABLE" && w > 10 && <circle cx={x0 + w - 4} cy={y0 + 5} r="3" fill="#fff" />}
              {w > 26 && text && (
                <text x={x0 + 1 + w / 2} y={y0 + laneH / 2 + 4} textAnchor="middle" fontSize="11" fontWeight="600" fill="#fff">{text}</text>
              )}
            </g>
          );
        })}
        {overlaps.map((o, i) => (
          <rect key={`ov${i}`} x={x(o.from)} y={top} width={Math.max(x(o.to) - x(o.from), 3)} height={2 * laneH + 6} fill="url(#hatch-red)"
            stroke={STATUS.critical} strokeWidth="1.5" pointerEvents="all" onClick={() => onSelect?.(o.a.activity_id)}
            onMouseMove={(e) => tt.show(e, <p className="text-danger"><b>Overlap</b> #{o.prev.sequence_number} and #{o.a.sequence_number}: {fmtDuration(o.to - o.from)}</p>)} onMouseLeave={tt.hide} />
        ))}
      </svg>
      {tt.node}
    </div>
  );
}
