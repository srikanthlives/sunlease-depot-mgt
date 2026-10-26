import { useParams, useSearchParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { Button, Spinner } from "../components/ui";
import ScheduleGantt from "../components/viz/ScheduleGantt";
import SummaryTiles from "../components/viz/SummaryTiles";
import { fmtDate, fmtDateLong, fmtDuration, label } from "../lib/format";
import { useApi } from "../lib/useApi";

export default function PrintTimetable() {
  const { versionId } = useParams();
  const [sp] = useSearchParams();
  const date = sp.get("date");
  const { data: t, error } = useApi(`/schedule-versions/${versionId}/print${date ? `?date=${date}` : ""}`);
  if (error) return <p className="p-6 text-danger">{error}</p>;
  if (!t) return <Spinner />;
  const trips = t.activities.filter((a) => a.trip);
  return (
    <div className="mx-auto max-w-[1100px] bg-white p-6 text-ink">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Sunlease · Planned bus schedule</p>
          <h1 className="text-xl font-semibold">{t.schedule_code} · {t.schedule_name}</h1>
          <p className="text-sm text-slate-600">Bus <b>{t.vehicle.fleet_number}</b> ({t.vehicle.registration_number}) · Operating date <b>{fmtDateLong(t.operating_date)}</b> · {t.timezone}</p>
          <p className="text-xs text-slate-500">Version {t.version_number} ({label(t.version_status)}) · valid {fmtDate(t.valid_from)} → {t.valid_to ? fmtDate(t.valid_to) : "open"} · printed {fmtDate(t.printed_at.slice(0, 10))}</p>
        </div>
        <Button icon={Printer} className="print:hidden" onClick={() => window.print()}>Print</Button>
      </div>
      <SummaryTiles summary={t.summary} />
      <div className="my-4"><ScheduleGantt compact activities={t.activities.map((a) => ({ ...a, origin_name: a.origin.name, destination_name: a.destination.name }))} operatingDate={t.operating_date} /></div>
      <table className="w-full border-collapse text-xs">
        <thead><tr className="border-b-2 border-ink text-left">
          <th className="py-1 pr-2">#</th><th className="pr-2">Activity</th><th className="pr-2">From</th><th className="pr-2">To</th><th className="pr-2">Start</th><th className="pr-2">End</th>
          <th className="pr-2 text-right">Duration</th><th className="pr-2 text-right">km</th><th className="pr-2">Details</th></tr></thead>
        <tbody>
          {t.activities.map((a) => (
            <tr key={a.activity_id} className="border-b border-slate-200 align-top">
              <td className="py-1 pr-2">{a.sequence_number}</td>
              <td className="pr-2">{label(a.activity_type)}{a.trip ? ` ${a.trip.trip_number}` : ""}</td>
              <td className="pr-2">{a.origin.name}</td><td className="pr-2">{a.destination.name}</td>
              <td className="whitespace-nowrap pr-2 tabular-nums">{fmtDate(a.start_date)} {a.start_time}</td>
              <td className="whitespace-nowrap pr-2 tabular-nums">{fmtDate(a.end_date)} {a.end_time}</td>
              <td className="pr-2 text-right tabular-nums">{fmtDuration(a.duration_minutes)}</td>
              <td className="pr-2 text-right tabular-nums">{a.distance_km || ""}</td>
              <td className="pr-2">
                {a.trip && `${a.trip.route_code} ${a.trip.direction_name}`}
                {a.movement && `${label(a.movement.movement_purpose)} · ${label(a.movement.payability_status)} · ${label(a.movement.payment_basis)}`}
                {a.charging && `SOC ${a.charging.start_soc ?? "—"}% → ${a.charging.end_soc ?? "—"}%${a.charging.expected_energy_kwh ? ` · ${a.charging.expected_energy_kwh} kWh` : ""}`}
                {a.halt && `Off service (not in cycle)${a.halt.start_soc !== null || a.halt.end_soc !== null ? ` · SOC ${a.halt.start_soc ?? "—"}% → ${a.halt.end_soc ?? "—"}%` : ""}`}
                {a.layover && `${label(a.layover.layover_purpose)}${a.layover.start_soc !== null || a.layover.end_soc !== null ? ` · SOC ${a.layover.start_soc ?? "—"}% → ${a.layover.end_soc ?? "—"}%` : ""}`}
                {a.remarks && <span className="block text-slate-500">{a.remarks}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {trips.length > 0 && (
        <>
          <h2 className="print-break mb-2 mt-6 text-base font-semibold">Stop timetables</h2>
          <div className="grid gap-4 md:grid-cols-2 print:grid-cols-2">
            {trips.map((a) => (
              <div key={a.activity_id} className="break-inside-avoid rounded border border-slate-300 p-2">
                <p className="mb-1 text-xs font-semibold">{a.trip.trip_number} · {a.trip.route_code} {a.trip.direction_name} · {a.trip.planned_distance_km} km</p>
                <table className="w-full text-[11px] [&_td]:px-1 [&_th]:px-1">
                  <thead><tr className="border-b border-slate-300 text-left"><th>Stop</th><th className="text-right">km</th><th>Arr</th><th>Dep</th><th className="text-right">SOC</th></tr></thead>
                  <tbody>
                    {a.trip.stops.map((s) => (
                      <tr key={s.scheduled_stop_time_id} className="border-b border-slate-100">
                        <td>{s.location.name}</td><td className="text-right tabular-nums">{s.cumulative_km}</td>
                        <td className="tabular-nums">{s.arrival || "—"}{s.arrival && s.arrival_date !== t.operating_date ? ` (${fmtDate(s.arrival_date).slice(0, 6)})` : ""}</td>
                        <td className="tabular-nums">{s.departure || "—"}{s.departure && s.departure_date !== t.operating_date ? ` (${fmtDate(s.departure_date).slice(0, 6)})` : ""}</td>
                        <td className="text-right tabular-nums">{s.soc !== null ? `${s.soc}%` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </>
      )}
      <p className="mt-6 text-[10px] text-slate-400">km are planned distances for checking against trip sheets; SOC values are planning references, not guaranteed readings.</p>
    </div>
  );
}
