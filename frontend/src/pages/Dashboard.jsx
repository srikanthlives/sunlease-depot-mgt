import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BusFront, CalendarClock, MapPin, Route, UserSquare2 } from "lucide-react";
import client from "../api/client";
import { Card, Empty, PageHeader, Spinner } from "../components/ui";
import ScheduleGantt from "../components/viz/ScheduleGantt";
import { fmtDateLong, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

export default function Dashboard() {
  const { data: vehicles } = useApi("/vehicles");
  const { data: schedules } = useApi("/schedules");
  const { data: routes } = useApi("/routes");
  const { data: locs } = useApi("/locations");
  const { data: emps } = useApi(`/employees?available_on=${todayIso()}`);
  const [today, setToday] = useState(null);
  useEffect(() => {
    (async () => {
      const { data } = await client.get(`/schedules?on_date=${todayIso()}&status=PUBLISHED`);
      const out = [];
      for (const s of data) {
        try { out.push((await client.get(`/schedules/${s.schedule_id}/timeline?date=${todayIso()}`)).data); } catch { /* none */ }
      }
      setToday(out);
    })();
  }, []);
  if (!vehicles || !schedules) return <Spinner />;
  const drafts = schedules.filter((s) => s.versions.some((v) => v.status === "DRAFT")).length;
  const tiles = [
    { to: "/schedules", icon: CalendarClock, label: "Schedules", value: schedules.length, sub: `${drafts} with a draft` },
    { to: "/vehicles", icon: BusFront, label: "Buses", value: vehicles.length, sub: `${vehicles.filter((v) => v.assigned_schedules.length).length} assigned` },
    { to: "/routes", icon: Route, label: "Routes", value: routes?.length ?? "…", sub: `${(routes || []).reduce((n, r) => n + r.directions.length, 0)} directions` },
    { to: "/locations", icon: MapPin, label: "Locations", value: locs?.length ?? "…", sub: `${(locs || []).filter((l) => l.supports_charging).length} with charging` },
    { to: "/employees", icon: UserSquare2, label: "Staff available today", value: emps?.length ?? "…", sub: `${(emps || []).filter((e) => e.staff_type === "DRIVER").length} drivers` },
  ];
  return (
    <>
      <PageHeader title="Overview" subtitle={fmtDateLong(todayIso())} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {tiles.map((t) => (
          <Link key={t.to} to={t.to} className="rounded-xl border border-slate-200 bg-white p-3 shadow-card hover:border-brand-300">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500"><t.icon className="h-3.5 w-3.5" />{t.label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{t.value}</p>
            <p className="text-xs text-slate-500">{t.sub}</p>
          </Link>
        ))}
      </div>
      <Card title="Buses in service today">
        {today === null ? <Spinner /> : today.length === 0 ? <Empty icon={CalendarClock} title="No published schedule operates today" /> : (
          <div className="space-y-5">
            {today.map((t) => (
              <div key={t.schedule_id}>
                <p className="mb-1 text-sm"><b>{t.vehicle.fleet_number}</b> · <Link to={`/schedules/${t.schedule_id}`} className="text-brand-600 hover:underline">{t.schedule_code} v{t.version_number}</Link>
                  <span className="text-slate-500"> · {t.summary.trip_count} trips · {t.summary.total_km} km</span></p>
                <ScheduleGantt compact activities={t.activities.map((a) => ({ ...a, origin_name: a.origin.name, destination_name: a.destination.name }))} operatingDate={t.operating_date} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
