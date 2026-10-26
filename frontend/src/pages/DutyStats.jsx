import { useState } from "react";
import { BarChart3, Download } from "lucide-react";
import { Button, Card, PageHeader, Spinner, Table } from "../components/ui";
import { DateInput } from "../components/inputs";
import { addDays, fmtDate, label, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

/**
 * Duty statistics over a stretch of days: who worked what, who stood in for whom, and how
 * often the roster held. Reads the recorded actuals, so only opened days count.
 */
export default function DutyStats() {
  const [from, setFrom] = useState(() => addDays(todayIso(), -30));
  const [to, setTo] = useState(todayIso);
  const { data, loading } = useApi(`/reports/duty-statistics?date_from=${from}&date_to=${to}`, null);

  const counts = data?.counts || {};
  const tiles = [
    ["Duty slots recorded", data?.slots ?? 0, ""],
    ["Ran as planned", counts.AS_PLANNED || 0, "text-slate-700"],
    ["Held", data?.as_planned_pct != null ? `${data.as_planned_pct}%` : "—", "text-slate-700"],
    ["Replaced", counts.REPLACED || 0, "text-brand-700"],
    ["Nobody worked it", counts.ABSENT || 0, "text-rose-700"],
    ["Not operated", counts.NOT_OPERATED || 0, "text-slate-500"],
  ];

  return (
    <>
      <PageHeader title="Duty statistics" subtitle="How the roster held up, and who actually worked"
        actions={<Button variant="secondary" icon={Download}
          onClick={() => window.open(`/api/reports/duty-statistics.xlsx?date_from=${from}&date_to=${to}`, "_blank")}>
          Excel</Button>} />

      <Card className="mb-3">
        <div className="flex flex-wrap items-end gap-3">
          <DateInput label="From" value={from} onChange={(v) => v && setFrom(v)} />
          <DateInput label="To" value={to} onChange={(v) => v && setTo(v)} />
          <p className="pb-2 text-xs text-slate-500">
            Only days that were opened on the duty day screen are counted.
          </p>
        </div>
      </Card>

      {loading && <div className="py-10 text-center"><Spinner /></div>}

      {!loading && data && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {tiles.map(([t, v, tone]) => (
              <div key={t} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">{t}</p>
                <p className={`text-lg font-semibold ${tone}`}>{v}</p>
              </div>
            ))}
          </div>

          {(data.top_reasons || []).length > 0 && (
            <Card className="mb-3" title="Why the roster changed">
              <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                {data.top_reasons.map((r) => (
                  <li key={r.reason} className="text-slate-600">
                    {r.reason} <b className="text-ink">{r.count}</b>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card padded={false} title={`${(data.crew || []).length} crew, ${fmtDate(from)} to ${fmtDate(to)}`}>
            <Table rowKey={(c) => c.employee_id} rows={data.crew || []} columns={[
              { key: "employee_number", title: "Emp. no.", className: "w-24 font-mono" },
              { key: "employee_name", title: "Name", className: "font-medium" },
              { key: "staff_type", title: "Type", className: "w-28", render: (c) => label(c.staff_type) },
              { key: "planned", title: "Planned", className: "w-20 text-right tabular-nums" },
              { key: "worked", title: "Worked", className: "w-20 text-right tabular-nums" },
              { key: "stood_in", title: "Stood in", className: "w-20 text-right tabular-nums",
                render: (c) => c.stood_in ? <span className="text-brand-700">{c.stood_in}</span> : "—" },
              { key: "missed", title: "Missed", className: "w-20 text-right tabular-nums",
                render: (c) => c.missed ? <span className="text-rose-700">{c.missed}</span> : "—" },
              { key: "spare", title: "Spare", className: "w-20 text-right tabular-nums",
                render: (c) => c.spare || "—" },
              { key: "shunting", title: "Shunting", className: "w-20 text-right tabular-nums",
                render: (c) => c.shunting || "—" },
              { key: "hours", title: "Hours", className: "w-20 text-right tabular-nums",
                render: (c) => c.minutes ? Math.round(c.minutes / 60 * 10) / 10 : "—" },
            ]} empty={<span className="inline-flex items-center gap-2"><BarChart3 className="h-4 w-4" /> No duty days recorded in this window</span>} />
          </Card>

          <p className="mt-2 text-xs text-slate-500">
            <b>Planned</b> counts duties the roster gave them; <b>worked</b> counts duties they
            actually did. <b>Stood in</b> is somebody else's duty they covered, <b>missed</b> is their
            own duty that somebody else did or nobody did. The two never have to agree: that gap is
            the point of the report. <b>Hours</b> adds up the stretches they actually held, so a duty
            handed over part-way counts as the part each person worked rather than a whole duty each.
          </p>
        </>
      )}
    </>
  );
}
