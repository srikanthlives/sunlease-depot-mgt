import { useMemo, useState } from "react";
import { ListChecks, Pencil, Plus, Trash2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Select, TextInput } from "../components/inputs";
import { label, options } from "../lib/format";
import { useApi } from "../lib/useApi";

const ATTRIBUTIONS = ["OPERATOR", "CLIENT", "EXTERNAL"];
const blank = { reason_code: "", reason_name: "", reason_name_local: "", default_attributable_to: "OPERATOR", is_active: true };

/**
 * Fault / cancellation reason codes, per company. These are what the driver writes on the paper
 * sheet as a number (the legend at the foot of the printed sheet lists them), and what the clerk
 * picks when a run was cut short or not run at all.
 */
export default function TripReasons() {
  const { can, canInCompany } = useAuth();
  const toast = useToast();
  const { data = [], reload } = useApi("/trip-reasons", []);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(null);
  const [errors, setErrors] = useState({});
  const rows = useMemo(() => (data || []).filter((r) =>
    !q || `${r.reason_code} ${r.reason_name} ${r.reason_name_local || ""}`.toLowerCase().includes(q.toLowerCase())), [data, q]);

  const save = async () => {
    const e = {};
    if (!edit.reason_code.trim()) e.reason_code = "Required";
    if (!edit.reason_name.trim()) e.reason_name = "Required";
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      if (edit.reason_id) await client.put(`/trip-reasons/${edit.reason_id}`, edit);
      else await client.post("/trip-reasons", edit);
      toast.ok(`Reason ${edit.reason_code} saved`);
      const wasNew = !edit.reason_id;
      reload();
      setEdit(wasNew ? { ...blank } : null);   // keep entering
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const remove = async (r) => {
    if (!window.confirm(`Delete ${r.reason_code}? Reasons already written on a trip sheet cannot be deleted - deactivate instead.`)) return;
    try {
      await client.delete(`/trip-reasons/${r.reason_id}`);
      toast.ok("Deleted");
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const toggle = async (r) => {
    try {
      await client.put(`/trip-reasons/${r.reason_id}`, { ...r, is_active: !r.is_active });
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const set = (k) => (v) => setEdit((x) => ({ ...x, [k]: v }));

  return (
    <>
      <PageHeader title="Reason codes"
        subtitle="Why a run was cut short or not run at all - printed as numbers in the legend of the paper trip sheet"
        actions={can("SCHEDULER") && <Button icon={Plus} onClick={() => { setErrors({}); setEdit({ ...blank }); }}>New reason</Button>} />
      <Card actions={<TextInput placeholder="Search code or name" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />}
        title={`${rows.length} reasons`} padded={false}>
        <Table rowKey={(r) => r.reason_id} rows={rows} onRowClick={(r) => canInCompany(r.company_id, "SCHEDULER") && (setErrors({}), setEdit({ ...r }))} columns={[
          { key: "reason_id", title: "No. on sheet", className: "w-28 font-mono", render: (r) => String(r.reason_id).padStart(3, "0") },
          { key: "reason_code", title: "Code", className: "font-medium" },
          { key: "reason_name", title: "Name", render: (r) => <>{r.reason_name}{r.reason_name_local && <span className="ml-1 text-xs text-slate-500">({r.reason_name_local})</span>}</> },
          { key: "default_attributable_to", title: "Attributable to", render: (r) => label(r.default_attributable_to) },
          { key: "is_active", title: "Status", render: (r) => <Badge value={r.is_active ? "ACTIVE" : "INACTIVE"} /> },
          { key: "x", title: "", className: "w-28 text-right", render: (r) => canInCompany(r.company_id, "SCHEDULER") && (
            <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
              <button tabIndex={-1} className="text-xs text-brand-600 hover:underline" onClick={() => toggle(r)}>{r.is_active ? "Deactivate" : "Activate"}</button>
              <IconButton icon={Pencil} title="Edit" onClick={() => setEdit({ ...r })} />
              <IconButton icon={Trash2} title="Delete (only if never used)" onClick={() => remove(r)} />
            </span>
          ) },
        ]} empty={<span className="inline-flex items-center gap-2"><ListChecks className="h-4 w-4" /> No reason codes yet</span>} />
      </Card>
      <p className="mt-2 text-xs text-slate-500">
        The number in the first column is what the driver writes in the <b>Reason #</b> boxes. It never changes once a
        reason exists, so printed sheets stay readable. Deactivating hides a reason from new entries but keeps it on
        sheets that already use it.
      </p>
      <Modal open={!!edit} title={edit?.reason_id ? `Edit ${edit.reason_code}` : "New reason"} onClose={() => setEdit(null)} onSave={save}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Code" required value={edit.reason_code} error={errors.reason_code}
              onChange={(e) => set("reason_code")(e.target.value.toUpperCase().replace(/\s+/g, "_"))} />
            <Select label="Attributable to" options={options(ATTRIBUTIONS)} value={edit.default_attributable_to}
              onChange={set("default_attributable_to")} />
            <TextInput label="Name" required className="col-span-2" value={edit.reason_name} error={errors.reason_name}
              onChange={(e) => set("reason_name")(e.target.value)} />
            <TextInput label="Name in regional language" className="col-span-2" value={edit.reason_name_local || ""}
              hint="Printed in brackets after the English name, e.g. వాహనం మొరాయించింది"
              onChange={(e) => set("reason_name_local")(e.target.value || null)} />
            <p className="col-span-2 text-xs text-slate-500">
              Attribution decides billing: losses attributable to the client are still billed by default, the
              operator's own faults are deducted. The clerk can override it on the sheet.
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}
