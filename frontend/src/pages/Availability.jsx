import { useMemo, useState } from "react";
import { CalendarOff, Pencil, Plus, Trash2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Combobox, DateInput, Select, TextArea, TextInput } from "../components/inputs";
import { addDays, fmtDate, label, options, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

const STATUSES = ["WEEKLY_OFF", "LEAVE", "SICK", "TRAINING", "OTHER"];
const blank = () => ({ employee_id: null, status: "LEAVE", from_date: todayIso(), to_date: todayIso(), remarks: "" });

const days = (from, to) => Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1;

/**
 * The availability register: when a driver or conductor cannot take a duty. A depot-level note
 * kept by the clerk, not HRMS leave approval - the roster reads it to warn before someone is
 * rostered on an off day, and the depot can still call them in and record why.
 */
export default function Availability() {
  const { can } = useAuth();
  const toast = useToast();
  const [from, setFrom] = useState(() => addDays(todayIso(), -7));
  const [to, setTo] = useState(() => addDays(todayIso(), 45));
  const { data = [], reload } = useApi(`/employee-availability?date_from=${from}&date_to=${to}`, [from, to]);
  const { data: employees = [] } = useApi("/employees", []);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(null);
  const [errors, setErrors] = useState({});

  const staff = useMemo(() => (employees || [])
    .filter((e) => e.staff_type !== "DEPOT_STAFF" && e.status === "ACTIVE")
    .map((e) => ({ value: e.employee_id, label: `${e.employee_number} - ${e.full_name}` })), [employees]);

  const rows = useMemo(() => (data || []).filter((r) =>
    !q || `${r.employee_number} ${r.employee_name} ${label(r.status)}`.toLowerCase().includes(q.toLowerCase())), [data, q]);

  const save = async () => {
    const e = {};
    if (!edit.employee_id) e.employee_id = "Required";
    if (!edit.from_date) e.from_date = "Required";
    if (!edit.to_date) e.to_date = "Required";
    else if (edit.from_date && edit.to_date < edit.from_date) e.to_date = "Cannot be before the first day";
    setErrors(e);
    if (Object.keys(e).length) return;
    const body = { ...edit, remarks: edit.remarks || null };
    try {
      if (edit.availability_id) await client.put(`/employee-availability/${edit.availability_id}`, body);
      else await client.post("/employee-availability", body);
      toast.ok("Availability saved");
      const wasNew = !edit.availability_id;
      reload();
      setEdit(wasNew ? { ...blank(), status: edit.status } : null);   // keep entering
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };

  const remove = async (r) => {
    if (!window.confirm(`Remove ${label(r.status)} for ${r.employee_name} (${fmtDate(r.from_date)} to ${fmtDate(r.to_date)})?`)) return;
    try {
      await client.delete(`/employee-availability/${r.availability_id}`);
      toast.ok("Removed");
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };

  const set = (k) => (v) => setEdit((x) => ({ ...x, [k]: v }));
  const open = (r) => { setErrors({}); setEdit(r ? { ...r } : blank()); };

  return (
    <>
      <PageHeader title="Availability register"
        subtitle="Days a driver or conductor cannot take a duty - the roster warns before rostering them"
        actions={can("MIS") && <Button icon={Plus} onClick={() => open(null)}>New entry</Button>} />

      <Card padded={false} title={`${rows.length} entries`} actions={
        <div className="flex flex-wrap items-end gap-2">
          <DateInput label="From" value={from} onChange={setFrom} compact />
          <DateInput label="To" value={to} onChange={setTo} compact />
          <TextInput placeholder="Search employee or reason" value={q} onChange={(e) => setQ(e.target.value)} className="w-56" />
        </div>
      }>
        <Table rowKey={(r) => r.availability_id} rows={rows} onRowClick={(r) => can("MIS") && open(r)} columns={[
          { key: "employee_number", title: "Number", className: "w-24 font-mono" },
          { key: "employee_name", title: "Employee", className: "font-medium" },
          { key: "staff_type", title: "Type", className: "w-28", render: (r) => label(r.staff_type) },
          { key: "status", title: "Not available for", className: "w-40", render: (r) => <Badge value={r.status} /> },
          { key: "from_date", title: "First day", className: "w-32", render: (r) => fmtDate(r.from_date) },
          { key: "to_date", title: "Last day", className: "w-32", render: (r) => fmtDate(r.to_date) },
          { key: "d", title: "Days", className: "w-16 text-right", render: (r) => days(r.from_date, r.to_date) },
          { key: "remarks", title: "Remarks", render: (r) => <span className="text-slate-500">{r.remarks}</span> },
          { key: "x", title: "", className: "w-20 text-right", render: (r) => can("MIS") && (
            <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
              <IconButton icon={Pencil} title="Edit" onClick={() => open(r)} />
              <IconButton icon={Trash2} title="Remove" onClick={() => remove(r)} />
            </span>
          ) },
        ]} empty={<span className="inline-flex items-center gap-2"><CalendarOff className="h-4 w-4" /> Nobody is marked unavailable in this window</span>} />
      </Card>

      <p className="mt-2 text-xs text-slate-500">
        Both dates are inclusive. Entries for one employee cannot overlap, so a leave that turns into sick leave is
        two entries, not two overlapping ones. This register is the depot's own note: it does not replace HRMS leave
        approval, and it never blocks a roster save - it only warns, so the clerk can still call somebody in on an
        off day and say why.
      </p>

      <Modal open={!!edit} title={edit?.availability_id ? `Edit ${edit.employee_name || "entry"}` : "New availability entry"}
        onClose={() => setEdit(null)} onSave={save}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            <Combobox label="Employee" required className="col-span-2" options={staff} value={edit.employee_id}
              error={errors.employee_id} autoFocus onChange={set("employee_id")}
              placeholder="Type a number or name" />
            <Select label="Not available for" required options={options(STATUSES)} value={edit.status}
              onChange={set("status")} />
            <div />
            <DateInput label="First day" required value={edit.from_date} error={errors.from_date}
              onChange={(v) => setEdit((x) => ({ ...x, from_date: v, to_date: x.to_date && x.to_date < v ? v : x.to_date }))} />
            <DateInput label="Last day" required value={edit.to_date} error={errors.to_date}
              base={edit.from_date} onChange={set("to_date")} />
            {edit.from_date && edit.to_date && edit.to_date >= edit.from_date && (
              <p className="col-span-2 -mt-1 text-xs text-slate-500">
                {days(edit.from_date, edit.to_date)} day(s), {fmtDate(edit.from_date)} to {fmtDate(edit.to_date)} inclusive.
              </p>
            )}
            <TextArea label="Remarks" className="col-span-2" value={edit.remarks || ""}
              onChange={(e) => set("remarks")(e.target.value)} />
          </div>
        )}
      </Modal>
    </>
  );
}
