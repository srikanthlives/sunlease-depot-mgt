import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ChevronDown, ChevronRight, ClipboardCheck, Download, FileWarning, Timer } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Empty, PageHeader, Spinner, Table } from "../components/ui";
import { DateInput } from "../components/inputs";
import { addDays, fmtDate, fmtDuration, label, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

const monthRange = (offset = 0) => {
  const t = new Date();
  const first = new Date(t.getFullYear(), t.getMonth() + offset, 1);
  const last = new Date(t.getFullYear(), t.getMonth() + offset + 1, 0);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return [iso(first), iso(last)];
};

/** From / to dates with month shortcuts (reports cover at most 92 days). */
function RangePicker({ range, setRange }) {
  const [from, to] = range;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <DateInput label="From" value={from} onChange={(v) => v && setRange([v, to])} className="w-40" />
      <DateInput label="To" value={to} base={from} onChange={(v) => v && setRange([from, v])} className="w-40" />
      <Button size="sm" variant="secondary" onClick={() => setRange(monthRange(0))}>This month</Button>
      <Button size="sm" variant="secondary" onClick={() => setRange(monthRange(-1))}>Last month</Button>
    </div>
  );
}

async function download(url, name, toast) {
  try {
    const r = await client.get(url, { responseType: "blob" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(r.data);
    a.download = name;
    a.click();
  } catch (e) {
    // blob error bodies need decoding before apiErrorMessage can read them
    try { e.response.data = JSON.parse(await e.response.data.text()); } catch { /* not json */ }
    toast.error(apiErrorMessage(e));
  }
}

const km = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 1 }));
const Num = ({ v, strong, muted }) => <span className={`tabular-nums ${strong ? "font-semibold text-ink" : muted ? "text-slate-500" : ""}`}>{km(v)}</span>;

// --------------------------------------------------------------------------
export function BillingReport() {
  const toast = useToast();
  const { isAll, costCenters, canIn, isSuper } = useAuth();
  const [range, setRange] = useState(() => monthRange(0));
  const [open, setOpen] = useState({});
  const { data, error } = useApi(`/reports/billing?date_from=${range[0]}&date_to=${range[1]}`);
  const canExport = isSuper || costCenters.some((m) => canIn(m.cost_center_id, "PUBLISHER"));
  return (
    <>
      <PageHeader title="Billing" subtitle="Approved trip sheets only: planned km, minus km lost to cancelled or cut-short runs (losses attributable to a billed party are not deducted)"
        actions={<>
          <RangePicker range={range} setRange={setRange} />
          {canExport && <Button icon={Download} onClick={() => download(`/reports/billing.xlsx?date_from=${range[0]}&date_to=${range[1]}`, `billing_${range[0]}_${range[1]}.xlsx`, toast)}>Excel</Button>}
        </>} />
      {error ? <Card><p className="text-sm text-danger">{error}</p></Card> : !data ? <Spinner /> : (
        <>
          {data.not_approved_sheets > 0 && (
            <p className="mb-3 flex items-center gap-2 rounded-md bg-warn/15 px-3 py-2 text-sm text-[#8a5a00]"><AlertTriangle className="h-4 w-4" />
              {data.not_approved_sheets} trip sheet{data.not_approved_sheets === 1 ? " is" : "s are"} in this period but not approved yet, so not billed. <Link to="/reports/missing-sheets" className="underline">See missing sheets</Link></p>
          )}
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[["Billable km", data.totals.billable_km, true], ["Planned billable km", data.totals.planned_billable_km], ["Deducted km", data.totals.deducted_km],
              ["Lost but billed km", data.totals.lost_billed_km], ["Bus-days billed", data.totals.days]].map(([k, v, s]) => (
              <div key={k} className="rounded-lg border border-slate-200 bg-white px-3 py-2"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className={`text-lg tabular-nums ${s ? "font-semibold" : ""}`}>{km(v)}</p></div>
            ))}
          </div>
          <Card title={`${data.rows.length} schedules`} padded={false}>
            {data.rows.length === 0 ? <Empty icon={ClipboardCheck} title="No approved trip sheets in this period" /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-right text-[11px] uppercase tracking-wide text-slate-500">
                    <tr><th className="px-3 py-2 text-left">Schedule</th>{isAll && <th className="px-2 text-left">Cost center</th>}<th className="px-2 text-left">Bus</th>
                      <th className="px-2">Days</th><th className="px-2">Planned</th><th className="px-2">Lost · operator</th><th className="px-2">Lost · client</th>
                      <th className="px-2">Lost · external</th><th className="px-2">Deducted</th><th className="px-2">Billable km</th><th className="px-2">Odometer</th><th className="px-3">Dev. %</th></tr>
                  </thead>
                  <tbody>
                    {data.rows.map((g) => {
                      const k = `${g.cost_center_id}-${g.schedule_id}`;
                      const days = data.daily.filter((d) => d.schedule_id === g.schedule_id);
                      return (
                        <Fragment key={k}>
                          <tr className="cursor-pointer border-t border-slate-100 text-right hover:bg-slate-50" onClick={() => setOpen((o) => ({ ...o, [k]: !o[k] }))}>
                            <td className="px-3 py-2 text-left font-medium"><span className="inline-flex items-center gap-1">{open[k] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}{g.schedule_code}</span></td>
                            {isAll && <td className="px-2 text-left">{g.cost_center}</td>}
                            <td className="px-2 text-left">{g.fleet_numbers}</td><td className="px-2 tabular-nums">{g.days}</td>
                            <td className="px-2"><Num v={g.planned_billable_km} /></td><td className="px-2"><Num v={g.lost_operator_km} muted /></td>
                            <td className="px-2"><Num v={g.lost_client_km} muted /></td><td className="px-2"><Num v={g.lost_external_km} muted /></td>
                            <td className="px-2"><Num v={g.deducted_km} /></td><td className="px-2"><Num v={g.billable_km} strong /></td>
                            <td className="px-2"><Num v={g.odometer_km} muted /></td>
                            <td className={`px-3 tabular-nums ${Math.abs(g.deviation_pct || 0) > 10 ? "text-[#8a5a00]" : "text-slate-500"}`}>{g.deviation_pct ?? "—"}</td>
                          </tr>
                          {open[k] && days.map((d) => (
                            <tr key={d.sheet_id} className="bg-slate-50/60 text-right text-xs">
                              <td className="px-3 py-1 text-left pl-9"><Link to={`/trip-sheets/${d.sheet_id}`} className="text-brand-600 hover:underline">{fmtDate(d.operating_date)}</Link>
                                {d.paper_sheet_no && <span className="ml-1 text-slate-400">#{d.paper_sheet_no}</span>}</td>
                              {isAll && <td />}<td className="px-2 text-left">{d.fleet_number}</td><td />
                              <td className="px-2"><Num v={d.planned_billable_km} /></td><td className="px-2"><Num v={d.lost_operator_km} muted /></td>
                              <td className="px-2"><Num v={d.lost_client_km} muted /></td><td className="px-2"><Num v={d.lost_external_km} muted /></td>
                              <td className="px-2"><Num v={d.deducted_km} /></td><td className="px-2"><Num v={d.billable_km} strong /></td>
                              <td className="px-2"><Num v={d.odometer_km} muted /></td><td />
                            </tr>
                          ))}
                        </Fragment>
                      );
                    })}
                    <tr className="border-t-2 border-slate-300 text-right font-semibold">
                      <td className="px-3 py-2 text-left">Total</td>{isAll && <td />}<td /><td className="px-2 tabular-nums">{data.totals.days}</td>
                      {["planned_billable_km", "lost_operator_km", "lost_client_km", "lost_external_km", "deducted_km", "billable_km", "odometer_km"].map((x) => <td key={x} className="px-2"><Num v={data.totals[x]} /></td>)}
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          {data.losses.length > 0 && (
            <Card title={`Lost km · ${data.losses.length} runs`} padded={false} className="mt-3">
              <Table rowKey={(r) => `${r.sheet_id}-${r.run}`} rows={data.losses} columns={[
                { key: "operating_date", title: "Date", render: (r) => <Link to={`/trip-sheets/${r.sheet_id}`} className="text-brand-600 hover:underline">{fmtDate(r.operating_date)}</Link> },
                { key: "schedule_code", title: "Schedule" }, { key: "fleet_number", title: "Bus" }, { key: "run", title: "Run" },
                { key: "status", title: "", render: (r) => <Badge value={r.status} /> },
                { key: "reason", title: "Reason", render: (r) => r.reason || "—" },
                { key: "attributable_to", title: "Attributable to", render: (r) => label(r.attributable_to).split(" (")[0] },
                { key: "lost_km", title: "Lost km", className: "text-right tabular-nums", render: (r) => `${km(r.lost_km)} of ${km(r.planned_km)}` },
                { key: "billed", title: "Billed", render: (r) => (r.billed ? <Badge value="PAYABLE">still billed</Badge> : <span className="text-xs text-slate-500">deducted</span>) },
              ]} />
            </Card>
          )}
        </>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
export function MissingSheets() {
  const { isAll, canIn } = useAuth();
  const [range, setRange] = useState(() => [addDays(todayIso(), -13), addDays(todayIso(), -1)]);
  const { data, error } = useApi(`/reports/missing-sheets?date_from=${range[0]}&date_to=${range[1]}`);
  return (
    <>
      <PageHeader title="Missing trip sheets" subtitle="Bus-days with a published schedule whose trip sheet is not approved yet" actions={<RangePicker range={range} setRange={setRange} />} />
      {error ? <Card><p className="text-sm text-danger">{error}</p></Card> : !data ? <Spinner /> : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[["Expected", data.expected], ...["NOT_STARTED", "DRAFT", "SUBMITTED", "APPROVED"].map((s) => [label(s), data.counts[s] || 0])].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-slate-200 bg-white px-3 py-2"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className="text-lg font-semibold tabular-nums">{v}</p></div>
            ))}
          </div>
          <Card title={`${data.rows.length} to chase`} padded={false}>
            {data.rows.length === 0 ? <Empty icon={ClipboardCheck} title="Every trip sheet in this period is approved" /> : (
              <Table rowKey={(r) => `${r.schedule_id}-${r.operating_date}`} rows={data.rows} columns={[
                { key: "operating_date", title: "Date", className: "tabular-nums whitespace-nowrap", render: (r) => fmtDate(r.operating_date) },
                ...(isAll ? [{ key: "cost_center", title: "Cost center" }] : []),
                { key: "fleet_number", title: "Bus", className: "font-medium" }, { key: "schedule_code", title: "Schedule", render: (r) => `${r.schedule_code} v${r.version_number}` },
                { key: "status", title: "Status", render: (r) => <Badge value={r.status} /> },
                { key: "x", title: "", className: "text-right", render: (r) => r.sheet_id
                  ? <Link to={`/trip-sheets/${r.sheet_id}`} className="text-sm text-brand-600 hover:underline">Open</Link>
                  : canIn(r.cost_center_id, "MIS") && <Link to={`/trip-sheets?date=${r.operating_date}`} className="text-sm text-brand-600 hover:underline">Go to board</Link> },
              ]} />
            )}
          </Card>
        </>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
export function CrewHours() {
  const toast = useToast();
  const { isAll, costCenters, canIn, isSuper } = useAuth();
  const [range, setRange] = useState(() => monthRange(0));
  const [open, setOpen] = useState({});
  const { data, error } = useApi(`/reports/crew-hours?date_from=${range[0]}&date_to=${range[1]}`);
  const canExport = isSuper || costCenters.some((m) => canIn(m.cost_center_id, "PUBLISHER"));
  const hm = (dt) => (dt ? `${fmtDate(dt.slice(0, 10)).slice(0, 6)} ${dt.slice(11, 16)}` : "—");
  return (
    <>
      <PageHeader title="Crew hours" subtitle="Duty time from trip sheets (all statuses), cut short where a driver change was recorded"
        actions={<>
          <RangePicker range={range} setRange={setRange} />
          {canExport && <Button icon={Download} onClick={() => download(`/reports/crew-hours.xlsx?date_from=${range[0]}&date_to=${range[1]}`, `crew_hours_${range[0]}_${range[1]}.xlsx`, toast)}>Excel</Button>}
        </>} />
      {error ? <Card><p className="text-sm text-danger">{error}</p></Card> : !data ? <Spinner /> : (
        <Card title={`${data.employees.length} staff · ${fmtDuration(data.total_minutes) || "0m"} on duty`} padded={false}>
          {data.employees.length === 0 ? <Empty icon={Timer} title="No crew recorded on trip sheets in this period" /> : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Employee</th><th className="px-2 text-right">Days</th><th className="px-2 text-right">Duties</th><th className="px-3 text-right">Hours</th></tr>
              </thead>
              <tbody>
                {data.employees.map((e) => (
                  <Fragment key={e.employee_id}>
                    <tr className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen((o) => ({ ...o, [e.employee_id]: !o[e.employee_id] }))}>
                      <td className="px-3 py-2"><span className="inline-flex items-center gap-1">{open[e.employee_id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        <b>{e.employee_name}</b> <span className="text-xs text-slate-500">{e.employee_number}</span>
                        {e.double_booked && <span className="ml-1 inline-flex items-center gap-0.5 text-xs text-danger"><FileWarning className="h-3.5 w-3.5" />double booked</span>}</span></td>
                      <td className="px-2 text-right tabular-nums">{e.days}</td><td className="px-2 text-right tabular-nums">{e.duties}</td>
                      <td className="px-3 text-right font-semibold tabular-nums">{fmtDuration(e.minutes) || "0m"}</td>
                    </tr>
                    {open[e.employee_id] && e.items.map((x) => (
                      <tr key={x.crew_id} className={`text-xs ${x.double_booked ? "bg-danger/5" : "bg-slate-50/60"}`}>
                        <td className="py-1 pl-9" colSpan={2}>
                          <Link to={`/trip-sheets/${x.sheet_id}`} className="text-brand-600 hover:underline">{fmtDate(x.operating_date)}</Link>
                          {" · "}{label(x.crew_role)} · {x.fleet_number} {x.schedule_code}{isAll ? ` (${x.cost_center})` : ""}{x.shift_name ? ` · shift ${x.shift_name}` : ""}
                          {x.took_over && <span className="text-slate-500"> · took over{x.handover_reason ? `: ${x.handover_reason}` : ""}</span>}
                          {" "}<Badge value={x.sheet_status} />
                        </td>
                        <td className="px-2 text-right tabular-nums text-slate-500">{hm(x.start)} → {hm(x.end)}</td>
                        <td className="px-3 text-right tabular-nums">{fmtDuration(x.minutes) || "0m"}</td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </>
  );
}
