import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { BusFront, ClipboardCheck, FilePlus2, FileScan, Printer, UserX } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Empty, PageHeader, Table } from "../components/ui";
import { ScanList, ScanUploadButton, StatusMark } from "../components/ScanUpload";
import { DateInput } from "../components/inputs";
import { addDays, fmtDateLong, label, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

const ORDER = ["NOT_STARTED", "DRAFT", "SUBMITTED", "APPROVED"];

/** Daily board: every bus with a published schedule on the date, and where its trip sheet stands. */
export default function TripSheets() {
  const nav = useNavigate();
  const toast = useToast();
  const { canIn, isAll, ccCode } = useAuth();
  const [sp] = useSearchParams();
  // paper sheets come in the day after, so start on yesterday (or the date asked for, e.g. from Missing sheets)
  const [date, setDate] = useState(() => sp.get("date") || addDays(todayIso(), -1));
  // undated: blank date boxes, so one print run can be reused on many days while the version is current
  const [undated, setUndated] = useState(false);
  const printSheets = (scheduleId) => window.open(`/print-sheets?date=${date}${scheduleId ? `&schedule=${scheduleId}` : ""}${undated ? "&undated=1" : ""}`, "_blank");
  const { data: rows = [], reload } = useApi(date ? `/trip-sheets/board?date=${date}` : null, []);
  // a clerk may upload where they may enter sheets
  const canUpload = (rows || []).some((r) => canIn(r.cost_center_id, "MIS"));
  const [busy, setBusy] = useState(null);
  const [scanKey, setScanKey] = useState(0);        // bumped after an upload, to refresh the list below
  const start = async (r) => {
    setBusy(r.schedule_id);
    try {
      const { data } = await client.post("/trip-sheets", { schedule_id: r.schedule_id, operating_date: date });
      nav(`/trip-sheets/${data.sheet_id}`);
    } catch (e) {
      toast.error(apiErrorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const counts = ORDER.map((s) => [s, (rows || []).filter((r) => r.status === s).length]);
  return (
    <>
      <PageHeader title="Trip sheets" subtitle="Enter each bus's paper trip sheet for the day, then submit it for approval"
        actions={<>
          <DateInput label="Operating date" value={date} onChange={(v) => v && setDate(v)} className="w-44" />
          {(rows || []).length > 0 && <>
            <label className="flex items-center gap-1.5 py-1.5 text-sm text-slate-600" title="Leave the date blank on the paper so the same printout can be used on any day while this schedule version is current">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={undated} onChange={(e) => setUndated(e.target.checked)} /> Undated (reusable)
            </label>
            <Button variant="secondary" icon={Printer} onClick={() => printSheets(null)} title="Pre-filled paper sheets for every bus, one per page">Print all sheets</Button>
            <ScanUploadButton date={date} canUpload={canUpload} onDone={() => { setScanKey((k) => k + 1); reload(); }} />
          </>}
        </>} />
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:max-w-3xl">
        {counts.map(([s, n]) => (
          <div key={s} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">{label(s)}</p>
            <p className="text-lg font-semibold tabular-nums">{n}</p>
          </div>
        ))}
      </div>
      <Card title={`${fmtDateLong(date)} · ${(rows || []).length} buses`} padded={false}>
        {(rows || []).length === 0 ? <Empty icon={ClipboardCheck} title="No published schedule operates on this date" /> : (
          <Table rowKey={(r) => r.schedule_id} rows={rows} onRowClick={(r) => r.sheet_id && nav(`/trip-sheets/${r.sheet_id}`)} columns={[
            ...(isAll ? [{ key: "cc", title: "Cost center", render: (r) => ccCode(r.cost_center_id) }] : []),
            { key: "fleet_number", title: "Bus", className: "font-medium", render: (r) => <span className="inline-flex items-center gap-2"><BusFront className="h-4 w-4 text-slate-400" />{r.fleet_number}</span> },
            { key: "schedule_code", title: "Schedule", render: (r) => `${r.schedule_code} v${r.version_number}` },
            { key: "schedule_name", title: "Name", className: "text-slate-500" },
            { key: "paper_sheet_no", title: "Paper sheet", render: (r) => r.paper_sheet_no || "—" },
            { key: "status", title: "Status", render: (r) => (
              <span className="inline-flex items-center gap-1.5">
                <Badge value={r.status} />
                {r.sheet_id > 0 && <StatusMark errors={r.validation_errors} warnings={r.validation_warnings}
                  title={r.validation_errors ? `${r.validation_errors} error${r.validation_errors === 1 ? "" : "s"} to fix before this sheet can be approved`
                    : r.validation_warnings ? `${r.validation_warnings} warning${r.validation_warnings === 1 ? "" : "s"} to check` : "Validation found nothing"} />}
                {r.crew_mismatch && <UserX className="h-3.5 w-3.5 text-amber-600"
                  title={`Not the rostered crew — ${r.crew_mismatch_text}`} />}
                {r.from_scan && <FileScan className="h-3.5 w-3.5 text-slate-400" title="Filled in from a scanned paper sheet" />}
              </span>) },
            { key: "p", title: "", className: "w-20 text-right", render: (r) => (
              <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" icon={Printer} title="Print the paper sheet for the driver"
                  onClick={(e) => { e.stopPropagation(); printSheets(r.schedule_id); }} />
                {/* one bus's paper: a page for any other bus or day is rejected, not applied */}
                <ScanUploadButton compact date={date} schedule={r} canUpload={canIn(r.cost_center_id, "MIS")}
                  onDone={() => { setScanKey((k) => k + 1); reload(); }} />
              </span>) },
            { key: "x", title: "", className: "w-32 text-right", render: (r) => r.sheet_id
              ? <Button size="sm" variant="secondary" onClick={(e) => { e.stopPropagation(); nav(`/trip-sheets/${r.sheet_id}`); }}>Open</Button>
              : canIn(r.cost_center_id, "MIS") && <Button size="sm" icon={FilePlus2} loading={busy === r.schedule_id} onClick={(e) => { e.stopPropagation(); start(r); }}>Start sheet</Button> },
          ]} />
        )}
      </Card>
      <ScanList date={date} canUpload={canUpload} reloadKey={scanKey} onDone={reload} />
    </>
  );
}
