import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarClock, Copy, Plus, Trash2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Empty, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Combobox, DateInput, TextInput } from "../components/inputs";
import { fmtDate, todayIso } from "../lib/format";
import { useApi } from "../lib/useApi";

function Validity({ versions }) {
  // effective_status says what a version means today: LIVE, SCHEDULED (starts later) or ENDED
  const pub = versions.filter((v) => v.status !== "DRAFT" && v.effective_status !== "ENDED");
  const draft = versions.find((v) => v.status === "DRAFT");
  return (
    <span className="flex flex-wrap items-center gap-1">
      {pub.slice(-2).map((v) => <Badge key={v.schedule_version_id} value={v.effective_status}>v{v.version_number} {v.effective_status === "SCHEDULED" ? `from ${fmtDate(v.valid_from)}` : "live"}</Badge>)}
      {draft && <Badge value="DRAFT">v{draft.version_number} draft</Badge>}
    </span>
  );
}

export default function Schedules() {
  const nav = useNavigate();
  const { can, canIn, isAll, ccCode } = useAuth();
  const toast = useToast();
  const { data = [], reload } = useApi("/schedules", []);
  const { data: vehicles = [] } = useApi("/vehicles", []);
  const [q, setQ] = useState("");
  const [form, setForm] = useState(null);         // new schedule, or (with source) a copy of one
  const [errors, setErrors] = useState({});
  const cloning = !!form?.source;
  const rows = useMemo(() => (data || []).filter((s) => !q || `${s.schedule_code} ${s.schedule_name} ${s.fleet_number}`.toLowerCase().includes(q.toLowerCase())), [data, q]);
  const busOpts = (vehicles || []).filter((v) => v.status === "ACTIVE").map((v) => ({ value: v.vehicle_id, label: v.fleet_number, sub: v.assigned_schedules.length ? `in ${v.assigned_schedules.join(", ")}` : "free" }));
  const save = async () => {
    const e = {};
    if (!form.schedule_code.trim()) e.schedule_code = "Required";
    if (!form.schedule_name.trim()) e.schedule_name = "Required";
    if (!form.vehicle_id) e.vehicle_id = "Required";
    if (!form.effective_from) e.effective_from = "Required";
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      const { source, ...body } = form;
      const { data: s } = source
        ? await client.post(`/schedules/${source.schedule_id}/clone`, body)
        : await client.post("/schedules", body);
      toast.ok(source ? `Copied ${source.schedule_code} into ${s.schedule_code} - a draft to edit and publish`
                    : `Schedule ${s.schedule_code} created - add its activities`);
      nav(`/schedules/${s.schedule_id}`);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  /** Copy a schedule onto another bus: same runs, as a fresh draft. */
  const clone = (r) => {
    setErrors({});
    setForm({
      source: r,
      schedule_code: `${r.schedule_code}-COPY`.slice(0, 30),
      schedule_name: `${r.schedule_name} (copy)`,
      vehicle_id: null,
      effective_from: todayIso(),
      effective_to: null,
    });
  };
  const remove = async (s) => {
    if (!window.confirm(`Delete schedule ${s.schedule_code} and all its activities? This cannot be undone.`)) return;
    try {
      await client.delete(`/schedules/${s.schedule_id}`);
      toast.ok(`Schedule ${s.schedule_code} deleted`);
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  return (
    <>
      <PageHeader title="Fixed bus schedules" subtitle="Recurring daily operating cycles, one physical bus each"
        actions={can("SCHEDULER") && <Button icon={Plus} onClick={() => { setErrors({}); setForm({ schedule_code: "", schedule_name: "", vehicle_id: null, effective_from: todayIso(), effective_to: null, timezone: "Asia/Kolkata", recurrence_type: "DAILY" }); }}>New schedule</Button>} />
      <Card title={`${rows.length} schedules`} padded={false} actions={<TextInput placeholder="Search code, name, bus" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />}>
        {(data || []).length === 0 ? <Empty icon={CalendarClock} title="No schedules yet">Create one and assign it to a bus.</Empty> : (
          <Table rowKey={(r) => r.schedule_id} rows={rows} onRowClick={(r) => nav(`/schedules/${r.schedule_id}`)} columns={[
            { key: "schedule_code", title: "Code", className: "font-medium" },
            { key: "schedule_name", title: "Name" },
            ...(isAll ? [{ key: "cc", title: "Cost center", render: (r) => ccCode(r.cost_center_id) }] : []),
            { key: "fleet_number", title: "Bus" },
            { key: "eff", title: "Effective", className: "tabular-nums whitespace-nowrap", render: (r) => `${fmtDate(r.effective_from)} → ${r.effective_to ? fmtDate(r.effective_to) : "open"}` },
            { key: "versions", title: "Versions", render: (r) => <Validity versions={r.versions} /> },
            { key: "status", title: "Status", render: (r) => <Badge value={r.status} /> },
            { key: "x", title: "", className: "w-20 text-right", render: (r) => canIn(r.cost_center_id, "SCHEDULER") && (
              <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
                <IconButton icon={Copy} title="Copy onto another bus as a draft" onClick={() => clone(r)} />
                {r.versions.every((v) => v.status === "DRAFT") &&
                  <IconButton icon={Trash2} title="Delete (never published)" onClick={() => remove(r)} />}
              </span>
            ) },
          ]} />
        )}
      </Card>
      <Modal open={!!form} title={cloning ? `Copy of ${form.source.schedule_code}` : "New schedule"}
        onClose={() => setForm(null)} onSave={save}>
        {form && (
          <div className="grid grid-cols-2 gap-3">
            {cloning && (
              <p className="col-span-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                The runs, crew pattern and shifts of <b>{form.source.schedule_code}</b> (the version in force on the
                date below) are copied into a <b>draft</b> on the bus you pick. Nothing is published until you
                validate and publish it.
              </p>
            )}
            <TextInput label="Schedule code" required value={form.schedule_code} error={errors.schedule_code} onChange={(e) => setForm({ ...form, schedule_code: e.target.value.toUpperCase() })} />
            <Combobox label="Bus" required options={busOpts} value={form.vehicle_id} error={errors.vehicle_id} onChange={(v) => setForm({ ...form, vehicle_id: v })} placeholder="Type fleet number" />
            <TextInput label="Schedule name" required className="col-span-2" value={form.schedule_name} error={errors.schedule_name} onChange={(e) => setForm({ ...form, schedule_name: e.target.value })} />
            <DateInput label="Effective from" required value={form.effective_from} error={errors.effective_from} onChange={(v) => setForm({ ...form, effective_from: v })} />
            <DateInput label="Effective to" value={form.effective_to} base={form.effective_from} onChange={(v) => setForm({ ...form, effective_to: v })} />
            {!cloning && <>
              <TextInput label="Timezone" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
              <TextInput label="Recurrence" value="Daily" disabled />
            </>}
          </div>
        )}
      </Modal>
    </>
  );
}
