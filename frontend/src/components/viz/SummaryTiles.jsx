import { BatteryCharging, Clock, Gauge, Hourglass, IndianRupee, Route, Sun, Moon, Timer } from "lucide-react";
import { fmtDuration, fmtRel } from "../../lib/format";
import { TYPE_COLOR } from "./colors";

function Tile({ icon: Icon, label, value, sub, swatch, title }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5" title={title}>
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {swatch ? <span className="h-2 w-2 rounded-sm" style={{ background: swatch }} /> : <Icon className="h-3.5 w-3.5" />}{label}
      </p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{value}</p>
      {sub && <p className="text-[11px] text-slate-500">{sub}</p>}
    </div>
  );
}

/** Non-revenue km split by payability (set per movement, independent of revenue). */
function payableSub(s) {
  const p = s.non_revenue_km_by_payability || {};
  const km = (v) => `${Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 1 })} km`;
  if (!s.non_revenue_km) return fmtDuration(s.minutes_by_type?.NON_REVENUE_MOVEMENT) || "0m";
  const parts = [`${km(p.PAYABLE)} payable`];
  if (p.NON_PAYABLE) parts.push(`${km(p.NON_PAYABLE)} non-payable`);
  if (p.TO_BE_CONFIRMED) parts.push(`${km(p.TO_BE_CONFIRMED)} to confirm`);
  return parts.join(" · ");
}

export default function SummaryTiles({ summary }) {
  if (!summary) return null;
  const s = summary;
  const km = (v) => `${Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 1 })} km`;
  const revPct = s.total_km ? Math.round((s.revenue_km / s.total_km) * 100) : 0;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5 2xl:grid-cols-9">
      <Tile icon={Gauge} label="Total km" value={km(s.total_km)} sub={s.total_km ? `${revPct}% revenue` : "—"} />
      <Tile icon={IndianRupee} label="Billable km" value={km(s.billable_km)}
        sub={s.total_km ? `${km(s.revenue_km)} trips + ${km(s.non_revenue_km_by_payability?.PAYABLE)} payable` : "—"} />
      <Tile swatch={TYPE_COLOR.PASSENGER_TRIP} label="Trips" value={s.trip_count} sub={km(s.revenue_km)} />
      <Tile swatch={TYPE_COLOR.NON_REVENUE_MOVEMENT} label="Non-revenue" value={km(s.non_revenue_km)} sub={payableSub(s)} />
      <Tile swatch={TYPE_COLOR.CHARGING} label="Charging" value={fmtDuration(s.minutes_by_type?.CHARGING) || "0m"} />
      <Tile swatch={TYPE_COLOR.LAYOVER} label="Layover" value={fmtDuration(s.minutes_by_type?.LAYOVER) || "0m"} />
      <Tile swatch={TYPE_COLOR.HALT} label="Halt" value={fmtDuration(s.halt_minutes) || "0m"} sub="depot / night halt · not in cycle" />
      <Tile icon={s.operating_spans_days > 1 ? Moon : Sun} label="Cycle" value={s.operating_minutes ? fmtDuration(s.operating_minutes) : "—"}
        title="First to last in-service activity, leaving out Halt time"
        sub={s.operating_minutes ? `${fmtRel(s.operating_start_min)} → ${fmtRel(s.operating_end_min)}${s.operating_spans_days > 1 ? ` · ${s.operating_spans_days} days` : ""}` : "No activities"} />
      <Tile icon={Timer} label="Steering time" value={fmtDuration(s.steering_minutes) || "0m"}
        sub={s.operating_minutes ? `trips + non-revenue · ${Math.round((s.steering_minutes / s.operating_minutes) * 100)}% of cycle` : "trips + non-revenue"} />
    </div>
  );
}

export { Tile, BatteryCharging, Clock, Hourglass, Route };
