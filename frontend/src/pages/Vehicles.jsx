import { useMemo, useState } from "react";
import { BusFront, Plus, Trash2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Combobox, NumberInput, Select, TextInput } from "../components/inputs";
import { options } from "../lib/format";
import { locOptions, useApi } from "../lib/useApi";

const blank = { fleet_number: "", registration_number: "", battery_capacity_kwh: null, home_depot_id: null, status: "ACTIVE" };

export default function Vehicles() {
  const { can, canIn, isAll, ccCode } = useAuth();
  const toast = useToast();
  const { data = [], reload } = useApi("/vehicles", []);
  const { data: locs = [] } = useApi("/locations", []);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(null);
  const [errors, setErrors] = useState({});
  const rows = useMemo(() => (data || []).filter((v) => !q || `${v.fleet_number} ${v.registration_number}`.toLowerCase().includes(q.toLowerCase())), [data, q]);
  const depots = locOptions(locs, (l) => l.location_type === "DEPOT");
  const set = (k) => (v) => setEdit((x) => ({ ...x, [k]: v }));
  const save = async () => {
    const e = {};
    if (!edit.fleet_number.trim()) e.fleet_number = "Required";
    if (!edit.registration_number.trim()) e.registration_number = "Required";
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      if (edit.vehicle_id) await client.put(`/vehicles/${edit.vehicle_id}`, edit);
      else await client.post("/vehicles", edit);
      toast.ok(`Bus ${edit.fleet_number} saved`);
      const wasNew = !edit.vehicle_id;
      reload();
      setEdit(wasNew ? { ...blank, home_depot_id: edit.home_depot_id, battery_capacity_kwh: edit.battery_capacity_kwh } : null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const remove = async (v) => {
    if (!window.confirm(`Delete bus ${v.fleet_number}?`)) return;
    try {
      await client.delete(`/vehicles/${v.vehicle_id}`);
      toast.ok(`Bus ${v.fleet_number} deleted`);
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const assigned = (data || []).filter((v) => v.assigned_schedules.length).length;
  return (
    <>
      <PageHeader title="Vehicles" subtitle="Physical buses. A schedule is always assigned to one of these."
        actions={can("SCHEDULER") && <Button icon={Plus} onClick={() => { setErrors({}); setEdit({ ...blank }); }}>New bus</Button>} />
      <div className="mb-3 grid grid-cols-3 gap-2 sm:max-w-lg">
        {[["Buses", (data || []).length], ["Assigned", assigned], ["Free", (data || []).filter((v) => v.status === "ACTIVE" && !v.assigned_schedules.length).length]].map(([k, v]) => (
          <div key={k} className="rounded-lg border border-slate-200 bg-white px-3 py-2"><p className="text-[11px] uppercase tracking-wide text-slate-500">{k}</p><p className="text-lg font-semibold tabular-nums">{v}</p></div>
        ))}
      </div>
      <Card title={`${rows.length} buses`} padded={false} actions={<TextInput placeholder="Search fleet or registration" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />}>
        <Table rowKey={(r) => r.vehicle_id} rows={rows} onRowClick={(r) => canIn(r.cost_center_id, "SCHEDULER") && (setErrors({}), setEdit({ ...r }))} columns={[
          { key: "fleet_number", title: "Fleet no.", className: "font-medium", render: (r) => <span className="inline-flex items-center gap-2"><BusFront className="h-4 w-4 text-slate-400" />{r.fleet_number}</span> },
          ...(isAll ? [{ key: "cc", title: "Cost center", render: (r) => ccCode(r.cost_center_id) }] : []),
          { key: "registration_number", title: "Registration" },
          { key: "battery_capacity_kwh", title: "Battery", className: "tabular-nums", render: (r) => r.battery_capacity_kwh ? `${Number(r.battery_capacity_kwh)} kWh` : "—" },
          { key: "home_depot_name", title: "Home depot", render: (r) => r.home_depot_name || "—" },
          { key: "assigned", title: "Published schedules", render: (r) => r.assigned_schedules.length
            ? <span className="flex flex-wrap gap-1">{r.assigned_schedules.map((s) => <Badge key={s} value="PAYABLE">{s}</Badge>)}</span>
            : <span className="text-xs text-slate-400">Free</span> },
          { key: "status", title: "Status", render: (r) => <Badge value={r.status} /> },
          { key: "x", title: "", className: "w-10 text-right", render: (r) => canIn(r.cost_center_id, "SCHEDULER") && !r.in_use && (
            <span onClick={(e) => e.stopPropagation()}><IconButton icon={Trash2} title="Delete (not used by any schedule)" onClick={() => remove(r)} /></span>
          ) },
        ]} />
      </Card>
      <Modal open={!!edit} title={edit?.vehicle_id ? `Edit ${edit.fleet_number}` : "New bus"} onClose={() => setEdit(null)} onSave={save}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Fleet number" required value={edit.fleet_number} error={errors.fleet_number} onChange={(e) => set("fleet_number")(e.target.value.toUpperCase())} />
            <TextInput label="Registration number" required value={edit.registration_number} error={errors.registration_number} onChange={(e) => set("registration_number")(e.target.value.toUpperCase())} />
            <NumberInput label="Battery capacity" suffix="kWh" min={0.1} value={edit.battery_capacity_kwh} onChange={set("battery_capacity_kwh")} />
            <Combobox label="Home depot" options={depots} value={edit.home_depot_id} onChange={set("home_depot_id")} placeholder="Type depot code or name" />
            <Select label="Status" options={options(["ACTIVE", "INACTIVE", "RETIRED"])} value={edit.status} onChange={set("status")} />
            {edit.assigned_schedules?.length > 0 && <p className="col-span-2 text-xs text-slate-500">Assigned to published schedule(s): {edit.assigned_schedules.join(", ")}. Retire them before deactivating this bus.</p>}
          </div>
        )}
      </Modal>
    </>
  );
}
