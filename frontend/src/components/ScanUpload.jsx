import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, FileScan, Images, Loader2, RefreshCw, Trash2, Upload, XCircle,
} from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import { Button, Card, IconButton, Modal, Table } from "./ui";
import ScanImage from "./ScanImage";
import { fmtDateLong } from "../lib/format";
import { useApi } from "../lib/useApi";

/** Error, warning or clean - the symbol a scanned page or a sheet carries. */
export function StatusMark({ errors = 0, warnings = 0, title }) {
  if (errors) return <XCircle className="h-4 w-4 text-rose-600" title={title || `${errors} error${errors === 1 ? "" : "s"}`} />;
  if (warnings) return <AlertTriangle className="h-4 w-4 text-amber-500" title={title || `${warnings} warning${warnings === 1 ? "" : "s"}`} />;
  return <CheckCircle2 className="h-4 w-4 text-emerald-600" title={title || "No problems found"} />;
}

const PAGE_TONE = { OK: "text-emerald-700", WARNED: "text-amber-600", UNREADABLE: "text-rose-600",
  SKIPPED: "text-slate-500", REJECTED: "text-rose-600" };

/** Every page of every upload in one list, so they can be looked through one after another. */
function flatten(scans) {
  return (scans || []).flatMap((s, si) => (s.pages || []).length
    ? s.pages.map((p) => ({ ...p, scan: s, scan_index: si }))
    : [{ page_no: 0, status: s.status === "FAILED" ? "UNREADABLE" : s.status, issues: [], errors: 1, warnings: 0,
         fields_read: 0, fields_unsure: 0, scan: s, scan_index: si }]);
}

/**
 * Pick the scanned PDFs and send them up. Several files can go at once.
 *
 * With `schedule`, the upload belongs to that one bus: paper for another bus, or another day, is
 * rejected rather than applied, so a sheet dropped on the wrong row cannot quietly overwrite it.
 */
export function ScanUploadButton({ date, canUpload, onDone, schedule, compact }) {
  const toast = useToast();
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(null);           // the uploads to look through

  const upload = async (files) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      const body = new FormData();
      [...files].forEach((f) => body.append("files", f));
      body.append("operating_date", date);
      if (schedule) body.append("schedule_id", schedule.schedule_id);
      const { data } = await client.post("/trip-sheets/scans", body);
      const scans = Array.isArray(data) ? data : [data];
      const pages = scans.flatMap((s) => s.pages || []);
      const failed = scans.filter((s) => s.status !== "DONE");
      const bad = pages.filter((p) => p.status === "UNREADABLE" || p.status === "SKIPPED").length;
      const warned = pages.filter((p) => p.warnings || p.fields_unsure).length;
      const what = `${scans.length} file${scans.length === 1 ? "" : "s"}, ${pages.length} page${pages.length === 1 ? "" : "s"}`;
      const rejected = pages.filter((p) => p.status === "REJECTED");
      if (rejected.length && rejected.length === pages.length) toast.error(rejected[0].issues[0]?.message || "This paper is not for that bus");
      else if (failed.length === scans.length) toast.error(failed[0]?.message || "The scan could not be read");
      else if (bad || failed.length) toast.error(`${what} read · ${bad + failed.length} could not be matched to a sheet - look through them`);
      else if (warned) toast.ok(`${what} read · ${warned} with something to check by hand`);
      else toast.ok(`${what} read into draft sheets`);
      setOpen(scans);
      onDone?.();
    } catch (e) {
      toast.error(apiErrorMessage(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (!canUpload) return null;
  const pick = (e) => { e.stopPropagation(); fileRef.current?.click(); };
  return (
    <>
      <input ref={fileRef} type="file" accept="application/pdf" multiple={!schedule} className="hidden"
        onClick={(e) => e.stopPropagation()} onChange={(e) => upload(e.target.files)} />
      {compact
        ? <IconButton icon={busy ? Loader2 : Upload} onClick={pick}
            title={`Upload the scanned paper sheet for ${schedule?.fleet_number || "this bus"}`} />
        : <Button variant="secondary" icon={Upload} loading={busy} onClick={pick}
            title={schedule ? `The scanned paper sheet for ${schedule.fleet_number}`
              : "Scanned PDFs of the paper sheets for this day - pick several files at once"}>
            {schedule ? "Upload this bus's sheet" : "Upload scanned sheets"}
          </Button>}
      <ScanViewer scans={open} onClose={() => setOpen(null)} />
    </>
  );
}

/** The uploads already made for this day, and what each page turned into. */
export function ScanList({ date, canUpload, reloadKey, onDone }) {
  const toast = useToast();
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const { data: scans = [], reload } = useApi(date ? `/trip-sheets/scans?operating_date=${date}&k=${reloadKey || 0}` : null, []);

  const show = async (rows) => {
    const full = await Promise.all(rows.map((x) => client.get(`/trip-sheets/scans/${x.scan_id}`).then((r) => r.data)));
    setOpen(full);
  };
  const reprocess = async (scan) => {
    setBusy(true);
    try {
      const { data } = await client.post(`/trip-sheets/scans/${scan.scan_id}/reprocess`);
      toast.ok("Read again");
      setOpen([data]);
      reload();
      onDone?.();
    } catch (e) {
      toast.error(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (scan) => {
    if (!window.confirm("Forget this upload? The draft sheets it filled stay as they are.")) return;
    try {
      await client.delete(`/trip-sheets/scans/${scan.scan_id}`);
      toast.ok("Upload removed");
      reload();
    } catch (e) {
      toast.error(apiErrorMessage(e));
    }
  };
  const live = (scans || []).filter((x) => x.status !== "SUPERSEDED");
  if (!(scans || []).length) return null;
  return (
    <>
      <Card className="mt-3" padded={false}
        title={`Scanned uploads · ${fmtDateLong(date)}`}
        actions={live.length > 0 && <Button size="sm" variant="secondary" icon={Images} loading={busy}
          onClick={() => show(live)}>Look through all pages</Button>}>
        <Table rowKey={(r) => r.scan_id} rows={scans} onRowClick={(r) => show([r])} columns={[
          { key: "file_name", title: "File", className: "font-medium", render: (r) => (
            <span className="inline-flex items-center gap-2"><FileScan className="h-4 w-4 text-slate-400" />{r.file_name}</span>) },
          { key: "page_count", title: "Pages", className: "tabular-nums" },
          { key: "status", title: "Result", render: (r) => r.status === "DONE"
            ? <span className="inline-flex items-center gap-1"><StatusMark errors={r.errors} warnings={r.warnings} />
                {r.errors ? `${r.errors} to fix` : r.warnings ? `${r.warnings} to check` : "clean"}</span>
            : <span className="text-slate-500">{r.status === "SUPERSEDED" ? "replaced by a later upload" : r.status.toLowerCase()}</span> },
          { key: "message", title: "", className: "text-xs text-rose-600", render: (r) => r.message || "" },
          { key: "x", title: "", className: "w-24 text-right", render: (r) => canUpload && r.status !== "SUPERSEDED" && (
            <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
              <IconButton icon={RefreshCw} title="Read this upload again" onClick={() => reprocess(r)} />
              <IconButton icon={Trash2} title="Forget this upload" onClick={() => remove(r)} />
            </span>) },
        ]} />
      </Card>
      <ScanViewer scans={open} onClose={() => setOpen(null)} />
    </>
  );
}

/**
 * The uploaded documents, one page at a time: the scanned paper on the left, what was read from it
 * on the right. Arrow keys and the buttons step through every page of every file in the batch.
 */
export function ScanViewer({ scans, onClose }) {
  const pages = flatten(scans);
  const [i, setI] = useState(0);
  useEffect(() => { setI(0); }, [scans]);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "ArrowRight") setI((x) => Math.min(x + 1, pages.length - 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(x - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pages.length]);
  if (!scans?.length) return null;
  const p = pages[Math.min(i, pages.length - 1)];
  const scan = p?.scan;
  const inFile = (scan.pages || []).length;
  return (
    <Modal open xwide onClose={onClose} footer={null} title={
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold text-ink">{scan.file_name}</h2>
        <span className="text-xs text-slate-500">
          document {p.scan_index + 1} of {scans.length}{inFile > 1 ? ` · page ${p.page_no} of ${inFile}` : ""}
        </span>
      </div>}>
      <div className="grid gap-4 md:grid-cols-[1.1fr_1fr]">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
          {p.page_no > 0 ? (
            <ScanImage path={`/trip-sheets/scans/${scan.scan_id}/pages/${p.page_no}/image`}
              alt={`Scanned page ${p.page_no}`} className="max-h-[62vh] w-full object-contain" />
          ) : (
            <p className="p-6 text-center text-sm text-slate-500">
              This file could not be opened as a PDF, so there is no page to show.
            </p>
          )}
        </div>
        <div className="space-y-3">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <StatusMark errors={p.errors} warnings={p.warnings} />
            <span className={PAGE_TONE[p.status] || ""}>{p.status.toLowerCase()}</span>
            {p.sheet_id
              ? <a className="text-brand-600 hover:underline" href={`/trip-sheets/${p.sheet_id}`}>open the trip sheet</a>
              : <span className="text-slate-500">not matched to a sheet</span>}
          </p>
          {scan.message && <p className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{scan.message}</p>}
          <p className="text-xs text-slate-500 tabular-nums">
            {p.fields_read} boxes read{p.fields_unsure ? ` · ${p.fields_unsure} to key in by hand` : " · nothing left to key in"}
          </p>
          {(p.issues || []).length > 0 && (
            <ul className="space-y-1 text-xs">
              {p.issues.map((x, k) => (
                <li key={k} className={x.severity === "ERROR" ? "text-rose-700" : "text-amber-700"}>
                  {x.severity === "ERROR" ? "✕" : "!"} {x.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <Button variant="secondary" icon={ChevronLeft} disabled={i === 0} onClick={() => setI(i - 1)}>Previous</Button>
        <span className="text-xs text-slate-500">page {Math.min(i, pages.length - 1) + 1} of {pages.length}</span>
        <Button variant="secondary" icon={ChevronRight} disabled={i >= pages.length - 1} onClick={() => setI(i + 1)}>Next</Button>
      </div>
    </Modal>
  );
}
