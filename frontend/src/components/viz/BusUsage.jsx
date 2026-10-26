import { INK, STATUS } from "./colors";
import { useTooltip } from "./Tooltip";
import { fmtRel } from "../../lib/format";

/**
 * Three consecutive operating days for one bus. Each lane = a schedule; bars = its daily occurrences.
 * Overlaps between any two bars are hatched red so a bus conflict is visible at a glance.
 * lanes: [{key, label, start_min, end_min, current}]
 */
export default function BusUsage({ lanes, days = 3 }) {
  const tt = useTooltip();
  const W = 1000, Lp = 110, laneH = 22, top = 20;
  const total = days * 1440;
  const x = (m) => Lp + (m / total) * (W - Lp - 8);
  const bars = [];
  lanes.forEach((l, li) => {
    if (l.start_min === null || l.start_min === undefined) return;
    for (let d = -1; d < days; d++) {
      const s = l.start_min + d * 1440, e = l.end_min + d * 1440;
      if (e <= 0 || s >= total) continue;
      bars.push({ li, s: Math.max(s, 0), e: Math.min(e, total), rs: s, re: e, l, d });
    }
  });
  const clashes = [];
  for (let i = 0; i < bars.length; i++)
    for (let j = i + 1; j < bars.length; j++) {
      const a = bars[i], b = bars[j];
      const s = Math.max(a.s, b.s), e = Math.min(a.e, b.e);
      if (s < e) clashes.push({ s, e, a, b });
    }
  const H = top + lanes.length * (laneH + 6) + 18;
  return (
    <div className="relative" data-tip-host>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Bus usage over three days">
        <defs>
          <pattern id="hatch-bus" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke={STATUS.critical} strokeWidth="2" />
          </pattern>
        </defs>
        {Array.from({ length: days + 1 }, (_, d) => (
          <g key={d}>
            <line x1={x(d * 1440)} x2={x(d * 1440)} y1={top - 6} y2={H - 16} stroke={INK.primary} strokeDasharray="3 3" />
            {d < days && <text x={x(d * 1440) + 4} y={12} fontSize="11" fontWeight="600" fill={INK.secondary}>Day {d + 1}</text>}
          </g>
        ))}
        {lanes.map((l, li) => (
          <text key={l.key} x={Lp - 8} y={top + li * (laneH + 6) + 15} textAnchor="end" fontSize="11" fontWeight={l.current ? 700 : 400} fill={INK.primary}>
            {l.label}
          </text>
        ))}
        {bars.map((b, i) => (
          <rect key={i} x={x(b.s)} y={top + b.li * (laneH + 6)} width={Math.max(x(b.e) - x(b.s) - 2, 2)} height={laneH} rx="4"
            fill={b.l.current ? "#2a78d6" : "#86b6ef"}
            onMouseMove={(e) => tt.show(e, <p><b>{b.l.label}</b> · {fmtRel(b.rs - b.d * 1440)} → {fmtRel(b.re - b.d * 1440)} (occurrence of day {b.d + 1})</p>)} onMouseLeave={tt.hide} />
        ))}
        {clashes.map((c, i) => {
          const y0 = top + Math.min(c.a.li, c.b.li) * (laneH + 6);
          const y1 = top + Math.max(c.a.li, c.b.li) * (laneH + 6) + laneH;
          return <rect key={`c${i}`} x={x(c.s)} y={y0} width={Math.max(x(c.e) - x(c.s), 3)} height={y1 - y0} fill="url(#hatch-bus)" stroke={STATUS.critical} strokeWidth="1.5"
            onMouseMove={(e) => tt.show(e, <p className="text-danger"><b>Bus conflict</b>: {c.a.l.label} and {c.b.l.label}</p>)} onMouseLeave={tt.hide} />;
        })}
      </svg>
      {tt.node}
      <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#2a78d6]" />This version</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#86b6ef]" />Other published schedules on this bus</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border border-danger bg-danger/20" />Conflict</span>
      </div>
    </div>
  );
}
