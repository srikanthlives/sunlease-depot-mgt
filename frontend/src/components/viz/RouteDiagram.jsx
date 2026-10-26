import { useTooltip } from "./Tooltip";
import { INK, STATUS } from "./colors";

/**
 * Proportional line diagram of one direction. stops: [{location_code, location_name, cumulative_distance_km, distance_from_previous_km}]
 * Flags: wrong first/last terminal (red ring), zero-length segment (dashed).
 */
export default function RouteDiagram({ title, stops, startTerminalId, endTerminalId, color = "#2a78d6", height = 112 }) {
  const tt = useTooltip();
  const W = 900;
  const pad = 56;
  if (!stops || stops.length === 0) {
    return <div className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-xs text-slate-400">Add stops to see the route diagram</div>;
  }
  const total = Number(stops[stops.length - 1].cumulative_distance_km) || 0;
  const x = (km) => (total > 0 ? pad + (Number(km) / total) * (W - pad * 2) : pad + 0);
  // when total is 0 (distances not entered yet) space stops evenly
  const xs = stops.map((s, i) => (total > 0 ? x(s.cumulative_distance_km) : pad + (i / Math.max(stops.length - 1, 1)) * (W - pad * 2)));
  const y = 52;
  const badStart = startTerminalId && stops[0].location_id !== startTerminalId;
  const badEnd = endTerminalId && stops[stops.length - 1].location_id !== endTerminalId;
  return (
    <div className="relative" data-tip-host>
      {title && (
        <div className="mb-1 flex items-baseline justify-between text-xs">
          <span className="font-semibold text-ink">{title}</span>
          <span className="tabular-nums text-slate-500">{stops.length} stops · {total.toLocaleString("en-IN", { maximumFractionDigits: 2 })} km</span>
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label={`${title || "Route"}: ${stops.map((s) => s.location_name).join(" to ")}`}>
        {stops.slice(1).map((s, i) => {
          const zero = Number(s.distance_from_previous_km) === 0;
          const mid = (xs[i] + xs[i + 1]) / 2;
          return (
            <g key={`seg${i}`}>
              <line x1={xs[i]} x2={xs[i + 1]} y1={y} y2={y} stroke={zero ? STATUS.warning : color} strokeWidth={zero ? 3 : 6}
                strokeDasharray={zero ? "4 4" : undefined} strokeLinecap="round" />
              {xs[i + 1] - xs[i] > 34 && (
                <text x={mid} y={y - 10} textAnchor="middle" fontSize="11" fill={INK.secondary} className="tabular-nums">
                  {Number(s.distance_from_previous_km).toLocaleString("en-IN", { maximumFractionDigits: 2 })} km
                </text>
              )}
            </g>
          );
        })}
        {stops.map((s, i) => {
          const terminal = i === 0 || i === stops.length - 1;
          const bad = (i === 0 && badStart) || (i === stops.length - 1 && badEnd);
          const below = i % 2 === 0;
          return (
            <g key={s.route_stop_id || `${s.location_id}-${i}`}
              onMouseMove={(e) => tt.show(e, (
                <div>
                  <p className="font-semibold">{s.location_name}</p>
                  <p>Stop {i + 1} · {Number(s.cumulative_distance_km).toLocaleString("en-IN")} km from start</p>
                  {i > 0 && <p>{Number(s.distance_from_previous_km)} km from previous</p>}
                  {bad && <p className="mt-1 font-medium text-danger">Must be the direction's {i === 0 ? "start" : "end"} terminal</p>}
                </div>
              ))} onMouseLeave={tt.hide}>
              <circle cx={xs[i]} cy={y} r={14} fill="transparent" />
              <circle cx={xs[i]} cy={y} r={terminal ? 9 : 6} fill={terminal ? color : "#fff"} stroke={bad ? STATUS.critical : color} strokeWidth={bad ? 4 : 3} />
              <text x={xs[i]} y={below ? y + 30 : y + 30} textAnchor="middle" fontSize="11" fontWeight={terminal ? 600 : 400} fill={bad ? STATUS.critical : INK.primary}>
                {/* long names are shortened on the line; the tooltip shows them in full */}
                {s.location_name.length > 16 ? `${s.location_name.slice(0, 15)}…` : s.location_name}
              </text>
              <text x={xs[i]} y={y + 45} textAnchor="middle" fontSize="10" fill={INK.muted} className="tabular-nums">
                {Number(s.cumulative_distance_km).toLocaleString("en-IN", { maximumFractionDigits: 1 })}
              </text>
            </g>
          );
        })}
      </svg>
      {tt.node}
    </div>
  );
}
