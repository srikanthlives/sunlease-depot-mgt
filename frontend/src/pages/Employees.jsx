import { useMemo, useRef, useState } from "react";
import { ArrowRightLeft, Download, Plus, RefreshCw, Upload } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Spinner, Table } from "../components/ui";
import { Checkbox, Combobox, DateInput, Select, TextInput } from "../components/inputs";
import { fmtDate, label, options, todayIso } from "../lib/format";
import { locOptions, useApi } from "../lib/useApi";

const blank = { employee_number: "", full_name: "", designation: "", staff_type: "DRIVER", home_depot_id: null, start_date: null, end_date: null, status: "ACTIVE" };

function Tenure({ e, on }) {
  const avail = e.status === "ACTIVE" && e.start_date <= on && (!e.end_date || e.end_date >= on);
  const ending = e.end_date && e.end_date >= on && (new Date(e.end_date) - new Date(on)) / 864e5 <= 60;
  return avail ? <Badge value={ending ? "TO_BE_CONFIRMED" : "ACTIVE"}>{ending ? `Leaves ${fmtDate(e.end_date)}` : "Available"}</Badge>
    : <Badge value="INACTIVE">{e.start_date > on ? `Joins ${fmtDate(e.start_date)}` : "Not available"}</Badge>;
}

export default function Employees() {
  const { can, canIn, cc, ccCode, costCenters } = useAuth();
  const toast = useToast();
  const { data = [], reload } = useApi("/employees", []);
  const { data: locs = [] } = useApi("/locations", []);
  const [q, setQ] = useState("");
  const [staff, setStaff] = useState(null);
  const [on, setOn] = useState(todayIso());
  const [edit, setEdit] = useState(null);
  const [errors, setErrors] = useState({});
  const [importResult, setImportResult] = useState(null);
  const [transfer, setTransfer] = useState(null);
  const [picked, setPicked] = useState([]);
  const [sync, setSync] = useState(null);
  const [busy, setBusy] = useState(false);
  const file = useRef(null);
  const rows = useMemo(() => (data || []).filter((e) => (!staff || e.staff_type === staff) &&
    (!q || `${e.employee_number} ${e.full_name} ${e.designation || ""}`.toLowerCase().includes(q.toLowerCase()))), [data, q, staff]);
  const depots = locOptions(locs, (l) => l.location_type === "DEPOT");

  /**
   * Transfer, for one employee or a whole selection: where they may go, and how many of them have
   * already been used here and so need their stint split rather than simply moved.
   */
  const openTransfer = async (people) => {
    try {
      const { data: usage } = await client.post("/employees-usage",
        { employee_ids: people.map((p) => p.employee_id) });
      const used = people.filter((p) => Object.keys(usage.used?.[p.employee_id] || {}).length);
      setTransfer({ people, used, usage: usage.used || {},
                    cost_center_id: null, effective_from: used.length ? todayIso() : null });
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const runTransfer = async () => {
    const { people, used, cost_center_id, effective_from } = transfer;
    if (!cost_center_id) return toast.error("Pick the cost center to move them to");
    if (used.length && !effective_from) return toast.error("Pick the first day at the new cost center");
    setBusy(true);
    try {
      const { data } = await client.post("/employees-transfer",
        { employee_ids: people.map((p) => p.employee_id), cost_center_id,
          effective_from: used.length ? effective_from : null });
      const parts = [data.moved && `${data.moved} moved`, data.transferred && `${data.transferred} re-stinted`];
      toast.ok(people.length === 1
        ? `${people[0].full_name} ${data.transferred ? `has a new stint at ${ccCode(cost_center_id)} from ${fmtDate(effective_from)}` : `moved to ${ccCode(cost_center_id)}`}`
        : `${parts.filter(Boolean).join(" · ")} to ${ccCode(cost_center_id)}`);
      setTransfer(null);
      setPicked([]);
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  /** Only rows you administer can be picked, and a batch cannot straddle two companies. */
  const movable = useMemo(() => rows.filter((r) => canIn(r.cost_center_id, "ADMIN")), [rows, canIn]);
  const selected = useMemo(() => (data || []).filter((e) => picked.includes(e.employee_id)), [data, picked]);
  const companyOf = (ccId) => costCenters.find((o) => o.cost_center_id === ccId)?.company_id;
  const mixedCompanies = new Set(selected.map((e) => companyOf(e.cost_center_id))).size > 1;
  const togglePick = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const pickAll = (on) => setPicked(on ? movable.map((r) => r.employee_id) : []);
  const set = (k) => (v) => setEdit((x) => ({ ...x, [k]: v }));
  const save = async () => {
    const e = {};
    if (!edit.employee_number.trim()) e.employee_number = "Required";
    if (!edit.full_name.trim()) e.full_name = "Required";
    if (!edit.start_date) e.start_date = "Required";
    if (edit.end_date && edit.start_date && edit.end_date < edit.start_date) e.end_date = "Cannot be before start date";
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      if (edit.employee_id) await client.put(`/employees/${edit.employee_id}`, edit);
      else await client.post("/employees", edit);
      toast.ok(`${edit.full_name} saved`);
      const wasNew = !edit.employee_id;
      reload();
      setEdit(wasNew ? { ...blank, staff_type: edit.staff_type, home_depot_id: edit.home_depot_id, start_date: edit.start_date } : null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const download = async () => {
    const r = await client.get("/employees-template", { responseType: "blob" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(r.data);
    a.download = "employee_template.xlsx";
    a.click();
  };
  const upload = async (f) => {
    if (!f) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await client.post("/employees-import", fd);
      setImportResult({ ...r.data, title: "Excel upload" });
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setBusy(false);
      file.current.value = "";
    }
  };
  /** Sync from HRMS is a two-step: preview what the payload holds, then pull only what is ticked. */
  const openSync = async () => {
    setSync({ loading: true, rows: [], picked: [] });
    try {
      const { data: p } = await client.get("/employees-hrms-preview");
      const rows = p.employees || [];
      setSync({ loading: false, rows, source_url: p.source_url,
                picked: rows.filter((r) => r.key && r.action === "NEW").map((r) => r.key) });
    } catch (err) {
      setSync(null);
      toast.error(apiErrorMessage(err));
    }
  };
  const toggle = (key) => setSync((s) => ({ ...s,
    picked: s.picked.includes(key) ? s.picked.filter((k) => k !== key) : [...s.picked, key] }));
  const toggleAll = (on) => setSync((s) => ({ ...s,
    picked: on ? s.rows.filter((r) => r.key).map((r) => r.key) : [] }));
  const runSync = async () => {
    if (!sync.picked.length) return toast.error("Tick the employees to sync");
    setBusy(true);
    try {
      const r = await client.post("/employees-sync-hrms", { keys: sync.picked });
      setSync(null);
      setImportResult({ ...r.data, title: "HRMS sync" });
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const avail = (data || []).filter((e) => e.status === "ACTIVE" && e.start_date <= on && (!e.end_date || e.end_date >= on));
  return (
    <>
      <PageHeader title="Employees" subtitle="Drivers, conductors and depot staff. One row per employment stint; the end date is the last working day."
        actions={can("SCHEDULER") && (
          <>
            <Button variant="secondary" icon={Download} onClick={download}>Template</Button>
            <Button variant="secondary" icon={Upload} loading={busy} onClick={() => file.current.click()}>Upload Excel</Button>
            <input ref={file} type="file" accept=".xlsx" className="hidden" onChange={(e) => upload(e.target.files[0])} />
            <Button variant="secondary" icon={RefreshCw} loading={busy} onClick={openSync}>Sync from HRMS</Button>
            <Button icon={Plus} onClick={() => { setErrors({}); setEdit({ ...blank }); }}>New employee</Button>
          </>
        )} />
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {["DRIVER", "CONDUCTOR", "DEPOT_STAFF"].map((t) => (
          <button key={t} onClick={() => setStaff(staff === t ? null : t)}
            className={`rounded-lg border px-3 py-2 text-left ${staff === t ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white"}`}>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">{t === "DEPOT_STAFF" ? "Depot staff" : `${label(t)}s`} available</p>
            <p className="text-lg font-semibold tabular-nums">{avail.filter((e) => e.staff_type === t).length}
              <span className="text-xs font-normal text-slate-400"> / {(data || []).filter((e) => e.staff_type === t).length}</span></p>
          </button>
        ))}
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
          <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Availability on</p>
          <DateInput value={on} onChange={(v) => setOn(v || todayIso())} />
        </div>
      </div>
      {selected.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm">
          <b className="tabular-nums">{selected.length} selected</b>
          {mixedCompanies && <span className="text-xs text-danger">They belong to different companies - an employee can only move within their own company.</span>}
          <span className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="secondary" onClick={() => setPicked([])}>Clear</Button>
            <Button size="sm" icon={ArrowRightLeft} disabled={mixedCompanies}
              onClick={() => openTransfer(selected)}>Move to another cost center</Button>
          </span>
        </div>
      )}
      <Card title={`${rows.length} employment records`} padded={false} actions={<TextInput placeholder="Search number, name, designation" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />}>
        <Table rowKey={(r) => r.employee_id} rows={rows} onRowClick={(r) => canIn(r.cost_center_id, "SCHEDULER") && (setErrors({}), setEdit({ ...r }))}
          rowClassName={(r) => picked.includes(r.employee_id) && "bg-brand-50"} columns={[
          ...(movable.length ? [{ key: "pick", className: "w-10",
            title: <Checkbox label="" checked={!!movable.length && picked.length === movable.length} onChange={pickAll} />,
            render: (r) => (canIn(r.cost_center_id, "ADMIN")
              ? <span onClick={(e) => e.stopPropagation()}><Checkbox label="" checked={picked.includes(r.employee_id)} onChange={() => togglePick(r.employee_id)} /></span>
              : <span className="text-slate-300">—</span>) }] : []),
          { key: "employee_number", title: "Emp. no.", className: "font-medium" },
          { key: "full_name", title: "Name" },
          { key: "cc", title: "Cost center", render: (r) => ccCode(r.cost_center_id) },
          { key: "designation", title: "Designation", render: (r) => r.designation || "—" },
          { key: "staff_type", title: "Staff type", render: (r) => label(r.staff_type) },
          { key: "home_depot_name", title: "Depot", render: (r) => r.home_depot_name || "—" },
          { key: "dates", title: "Employment", className: "tabular-nums whitespace-nowrap", render: (r) => `${fmtDate(r.start_date)} → ${r.end_date ? fmtDate(r.end_date) : "present"}` },
          { key: "avail", title: `On ${fmtDate(on)}`, render: (r) => <Tenure e={r} on={on} /> },
          { key: "source", title: "Source", render: (r) => <span className="text-xs text-slate-500">{label(r.source)}</span> },
          { key: "x", title: "", className: "w-10 text-right", render: (r) => canIn(r.cost_center_id, "ADMIN") && (
            <span onClick={(e) => e.stopPropagation()}>
              <IconButton icon={ArrowRightLeft} title="Move to another cost center" onClick={() => openTransfer([r])} />
            </span>
          ) },
        ]} />
      </Card>
      <Modal open={!!edit} title={edit?.employee_id ? `Edit ${edit.employee_number}` : "New employee stint"} onClose={() => setEdit(null)} onSave={save}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Employee number" required value={edit.employee_number} error={errors.employee_number} onChange={(e) => set("employee_number")(e.target.value.toUpperCase())} />
            <Select label="Staff type" options={options(["DRIVER", "CONDUCTOR", "DEPOT_STAFF"])} value={edit.staff_type} onChange={set("staff_type")} />
            <TextInput label="Full name" required className="col-span-2" value={edit.full_name} error={errors.full_name} onChange={(e) => set("full_name")(e.target.value)} />
            <TextInput label="Designation" value={edit.designation || ""} onChange={(e) => set("designation")(e.target.value)} />
            <Combobox label="Home depot" options={depots} value={edit.home_depot_id} onChange={set("home_depot_id")} />
            <DateInput label="Start date" required value={edit.start_date} error={errors.start_date} onChange={set("start_date")} />
            <DateInput label="End date (last working day)" value={edit.end_date} base={edit.start_date} error={errors.end_date} onChange={set("end_date")} />
            <Select label="Status" options={options(["ACTIVE", "INACTIVE"])} value={edit.status} onChange={set("status")} />
            <p className="col-span-2 text-xs text-slate-500">
              {edit.employee_id
                ? <>This stint belongs to cost center <b>{ccCode(edit.cost_center_id)}</b>.</>
                : <>The stint is created in the cost center you are working in, <b>{ccCode(cc)}</b>.</>}{" "}
              Crew can only be rostered onto buses of their own cost center, so use <b>Move to another cost
              center</b> if this is the wrong depot.
            </p>
            <p className="col-span-2 text-xs text-slate-500">A rejoiner gets a new stint with the same employee number and a new start date. Stints cannot overlap.</p>
          </div>
        )}
      </Modal>
      <Modal open={!!transfer} wide={transfer?.people.length > 1}
        title={transfer ? (transfer.people.length === 1 ? `Move ${transfer.people[0].full_name}` : `Move ${transfer.people.length} employees`) : ""}
        onClose={() => setTransfer(null)} onSave={runTransfer}>
        {transfer && (
          <div className="space-y-3">
            <Select label="Move to cost center" required value={transfer.cost_center_id || ""}
              onChange={(v) => setTransfer({ ...transfer, cost_center_id: Number(v) })}
              options={costCenters
                .filter((m) => !transfer.people.every((p) => p.cost_center_id === m.cost_center_id)
                  && m.role === "ADMIN" && m.company_id === companyOf(transfer.people[0].cost_center_id))
                .map((m) => ({ value: m.cost_center_id, label: `${m.cost_center_code} - ${m.cost_center_name}`,
                               sub: m.company_name }))}
              placeholder="No other cost center of this company that you administer" />
            {transfer.used.length === 0 ? (
              <p className="text-xs text-slate-500">
                {transfer.people.length === 1 ? "This stint is" : `None of these ${transfer.people.length} stints are`} used
                anywhere yet, so {transfer.people.length === 1 ? "it simply moves" : "they simply move"} to the
                other cost center - nothing else changes.
              </p>
            ) : (
              <>
                <DateInput label="First day at the new cost center" required value={transfer.effective_from}
                  base={transfer.people.map((p) => p.start_date).sort().slice(-1)[0]}
                  onChange={(v) => setTransfer({ ...transfer, effective_from: v })} />
                <p className="text-xs text-slate-500">
                  {transfer.used.length} of {transfer.people.length} {transfer.used.length === 1 ? "has" : "have"} already
                  been used here, so {transfer.used.length === 1 ? "that stint" : "those stints"} end the day before and
                  new ones start at the other cost center. The duties and trip sheets already recorded stay with this
                  depot. {transfer.people.length > transfer.used.length
                    && `The other ${transfer.people.length - transfer.used.length} simply move across.`}
                </p>
              </>
            )}
            {transfer.people.length > 1 && (
              <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <tr><th className="px-2 py-1.5">Emp. no.</th><th className="px-2 py-1.5">Name</th>
                      <th className="px-2 py-1.5">From</th><th className="px-2 py-1.5">Used here</th></tr>
                  </thead>
                  <tbody>
                    {transfer.people.map((p) => {
                      const u = Object.entries(transfer.usage[p.employee_id] || {});
                      return (
                        <tr key={p.employee_id} className="border-t border-slate-100">
                          <td className="px-2 py-1 font-medium">{p.employee_number}</td>
                          <td className="px-2 py-1">{p.full_name}</td>
                          <td className="px-2 py-1 text-slate-500">{ccCode(p.cost_center_id)}</td>
                          <td className="px-2 py-1 text-xs text-slate-500">
                            {u.length ? u.map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ")
                              : <span className="text-slate-400">not used - plain move</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {transfer.people.length > 1 && (
              <p className="text-xs text-slate-500">
                The whole batch is applied together: if any one of them cannot move, nothing does and you
                are told why.
              </p>
            )}
          </div>
        )}
      </Modal>
      <Modal open={!!sync} xwide title="Sync from HRMS"
        onClose={() => setSync(null)} onSave={runSync}
        footer={sync && !sync.loading ? (
          <>
            <Button variant="secondary" onClick={() => setSync(null)} type="button">Cancel</Button>
            <Button loading={busy} onClick={runSync} type="button"
              disabled={!sync.picked.length}>Sync {sync.picked.length} selected</Button>
          </>
        ) : <Button variant="secondary" onClick={() => setSync(null)} type="button">Cancel</Button>}>
        {sync?.loading && <Spinner />}
        {sync && !sync.loading && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              {sync.rows.length} employee record(s) from <span className="font-mono">{sync.source_url}</span>.
              Tick the ones to pull into <b>{ccCode(cc)}</b>. New stints are ticked for you; nothing is
              written until you press Sync.
            </p>
            <Table rowKey={(r) => r.key || `bad-${r.row}`} rows={sync.rows}
              empty="HRMS returned no employees"
              rowClassName={(r) => r.action === "BLOCKED" && "bg-danger/5"}
              columns={[
                { key: "pick", className: "w-10",
                  title: <Checkbox label="" checked={sync.rows.some((r) => r.key) && sync.picked.length === sync.rows.filter((r) => r.key).length}
                    onChange={toggleAll} />,
                  render: (r) => (r.key
                    ? <Checkbox label="" checked={sync.picked.includes(r.key)} onChange={() => toggle(r.key)} />
                    : <span className="text-slate-300">—</span>) },
                { key: "employee_number", title: "Emp. no.", className: "font-medium" },
                { key: "full_name", title: "Name" },
                { key: "designation", title: "Designation", render: (r) => r.designation || "—" },
                { key: "staff_type", title: "Staff type", render: (r) => (r.staff_type ? label(r.staff_type) : "—") },
                { key: "home_depot_code", title: "Depot", render: (r) => r.home_depot_code || "—" },
                { key: "dates", title: "Employment", className: "tabular-nums whitespace-nowrap",
                  render: (r) => (r.start_date ? `${fmtDate(r.start_date)} → ${r.end_date ? fmtDate(r.end_date) : "present"}` : "—") },
                { key: "action", title: "Will", render: (r) => (
                  <Badge value={r.action === "NEW" ? "ACTIVE" : r.action === "UPDATE" ? "TO_BE_CONFIRMED" : "INACTIVE"}>
                    {r.action === "NEW" ? "Create" : r.action === "UPDATE" ? "Update" : "Cannot sync"}
                  </Badge>) },
                { key: "error", title: "", render: (r) => r.error
                  ? <span className="text-xs text-danger">{r.error}</span> : null },
              ]} />
          </div>
        )}
      </Modal>
      <Modal open={!!importResult} title={importResult?.title} onClose={() => setImportResult(null)} footer={<Button onClick={() => setImportResult(null)}>Close</Button>}>
        {importResult && (
          <div className="space-y-3 text-sm">
            <p><b>{importResult.created}</b> created · <b>{importResult.updated}</b> updated</p>
            {importResult.errors.length > 0 && (
              <>
                <p className="font-medium text-danger">{importResult.errors.length} problem(s){importResult.title === "Excel upload" ? " - nothing was saved. Fix the file and upload again." : ""}</p>
                <ul className="max-h-60 space-y-1 overflow-auto text-xs">
                  {importResult.errors.map((e, i) => <li key={i}>{e.row ? `Row ${e.row}: ` : ""}{e.error}</li>)}
                </ul>
              </>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
