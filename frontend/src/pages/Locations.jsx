import { useMemo, useState } from "react";
import { MapPin, Pencil, Plus, Trash2, Zap } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Checkbox, NumberInput, Select, TextInput } from "../components/inputs";
import { label, options } from "../lib/format";
import { useApi } from "../lib/useApi";

const TYPES = ["DEPOT", "TERMINAL", "BUS_STOP", "CHARGING_POINT", "OTHER"];
const blank = { location_code: "", location_name: "", location_name_local: "", location_type: "BUS_STOP", supports_charging: false, latitude: null, longitude: null, is_active: true };

export default function Locations() {
  const { can, canInCompany } = useAuth();
  const toast = useToast();
  const { data = [], reload } = useApi("/locations", []);
  const [q, setQ] = useState("");
  const [type, setType] = useState(null);
  const [edit, setEdit] = useState(null);
  const [errors, setErrors] = useState({});
  const rows = useMemo(() => (data || []).filter((l) =>
    (!type || l.location_type === type) && (!q || `${l.location_code} ${l.location_name}`.toLowerCase().includes(q.toLowerCase()))), [data, q, type]);

  const save = async () => {
    const e = {};
    if (!edit.location_code.trim()) e.location_code = "Required";
    if (!edit.location_name.trim()) e.location_name = "Required";
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      if (edit.location_id) await client.put(`/locations/${edit.location_id}`, edit);
      else await client.post("/locations", edit);
      toast.ok(`Location ${edit.location_code} saved`);
      const wasNew = !edit.location_id;
      reload();
      // keep entering: a fresh form with the same type
      setEdit(wasNew ? { ...blank, location_type: edit.location_type, supports_charging: edit.supports_charging } : null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const remove = async (l) => {
    if (!window.confirm(`Delete ${l.location_code}?`)) return;
    try {
      await client.delete(`/locations/${l.location_id}`);
      toast.ok("Deleted");
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const toggle = async (l) => {
    try {
      await client.put(`/locations/${l.location_id}`, { ...l, is_active: !l.is_active });
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const set = (k) => (v) => setEdit((x) => ({ ...x, [k]: v }));

  const counts = TYPES.map((t) => [t, (data || []).filter((l) => l.location_type === t).length]);
  return (
    <>
      <PageHeader title="Locations" subtitle="Depots, terminals, stops and charging points - shared by every cost center of the company"
        actions={can("SCHEDULER") && <Button icon={Plus} onClick={() => { setErrors({}); setEdit({ ...blank }); }}>New location</Button>} />
      <div className="mb-3 flex flex-wrap gap-2">
        <button onClick={() => setType(null)} className={`rounded-full px-3 py-1 text-xs ${!type ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}>All · {(data || []).length}</button>
        {counts.map(([t, n]) => (
          <button key={t} onClick={() => setType(t)} className={`rounded-full px-3 py-1 text-xs ${type === t ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}>{label(t)} · {n}</button>
        ))}
      </div>
      <Card actions={<TextInput placeholder="Search code or name" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />} title={`${rows.length} locations`} padded={false}>
        <Table rowKey={(r) => r.location_id} rows={rows} onRowClick={(r) => canInCompany(r.company_id, "SCHEDULER") && (setErrors({}), setEdit({ ...r }))} columns={[
          { key: "location_code", title: "Code", className: "font-medium" },
          { key: "location_name", title: "Name", render: (r) => <>{r.location_name}{r.location_name_local && <span className="ml-1 text-xs text-slate-500">({r.location_name_local})</span>}</> },
          { key: "location_type", title: "Type", render: (r) => label(r.location_type) },
          { key: "supports_charging", title: "Charging", render: (r) => r.supports_charging ? <span className="inline-flex items-center gap-1 text-[#127a55]"><Zap className="h-3.5 w-3.5" /> Yes</span> : <span className="text-slate-400">No</span> },
          { key: "is_active", title: "Status", render: (r) => <Badge value={r.is_active ? "ACTIVE" : "INACTIVE"} /> },
          { key: "x", title: "", className: "w-28 text-right", render: (r) => canInCompany(r.company_id, "SCHEDULER") && (
            <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
              <button tabIndex={-1} className="text-xs text-brand-600 hover:underline" onClick={() => toggle(r)}>{r.is_active ? "Deactivate" : "Activate"}</button>
              <IconButton icon={Pencil} title="Edit" onClick={() => setEdit({ ...r })} />
              <IconButton icon={Trash2} title="Delete (only if unused)" onClick={() => remove(r)} />
            </span>
          ) },
        ]} empty={<span className="inline-flex items-center gap-2"><MapPin className="h-4 w-4" /> No locations yet</span>} />
      </Card>
      <Modal open={!!edit} title={edit?.location_id ? `Edit ${edit.location_code}` : "New location"} onClose={() => setEdit(null)} onSave={save}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Code" required value={edit.location_code} error={errors.location_code} onChange={(e) => set("location_code")(e.target.value.toUpperCase())} />
            <Select label="Type" options={options(TYPES)} value={edit.location_type} onChange={(v) => { set("location_type")(v); if (v === "CHARGING_POINT") set("supports_charging")(true); }} />
            <TextInput label="Name" required className="col-span-2" value={edit.location_name} error={errors.location_name} onChange={(e) => set("location_name")(e.target.value)} />
            <TextInput label="Name in regional language" className="col-span-2" value={edit.location_name_local || ""} hint="Printed in brackets on trip sheets, e.g. భోగాపురం"
              onChange={(e) => set("location_name_local")(e.target.value || null)} />
            <Checkbox label="Supports charging" checked={edit.supports_charging} onChange={set("supports_charging")} className="col-span-2" />
            <NumberInput label="Latitude" min={-90} max={90} value={edit.latitude} onChange={set("latitude")} />
            <NumberInput label="Longitude" min={-180} max={180} value={edit.longitude} onChange={set("longitude")} />
          </div>
        )}
      </Modal>
    </>
  );
}
