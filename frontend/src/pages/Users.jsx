import { useState } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Modal, PageHeader, Table } from "../components/ui";
import { Checkbox, Select, TextInput } from "../components/inputs";
import { label } from "../lib/format";
import { useApi } from "../lib/useApi";

const ROLES = ["VIEWER", "MIS", "SCHEDULER", "PUBLISHER", "ADMIN"];
const ROLE_HELP = {
  VIEWER: "View only", MIS: "Enter and submit trip sheets; view everything else", SCHEDULER: "Edit masters and draft schedules", PUBLISHER: "Also publish, unpublish and retire",
  ADMIN: "Everything in the cost center, plus its settings and audit log",
};

/** One row per cost center: pick the user's role there, or none. */
function RoleGrid({ costCenters, roles, onChange }) {
  const byCc = Object.fromEntries(roles.map((r) => [r.cost_center_id, r.role]));
  const set = (ccId, role) => onChange([...roles.filter((r) => r.cost_center_id !== ccId), ...(role ? [{ cost_center_id: ccId, role }] : [])]);
  const companies = [...new Map(costCenters.map((c) => [c.company_id, c.company_name])).entries()];
  if (!costCenters.length) return <p className="text-xs text-slate-500">No cost centers yet - create them under Organisation.</p>;
  return (
    <div className="max-h-80 overflow-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
          <tr><th className="px-3 py-1.5">Cost center</th><th className="px-3 py-1.5">Role</th></tr>
        </thead>
        <tbody>
          {companies.map(([id, name]) => [
            <tr key={`co${id}`} className="bg-slate-50/60"><td colSpan={2} className="px-3 py-1 text-xs font-semibold text-slate-600">{name}</td></tr>,
            ...costCenters.filter((c) => c.company_id === id).map((c) => (
              <tr key={c.cost_center_id} className="border-t border-slate-100">
                <td className="px-3 py-1.5"><span className="font-medium">{c.cost_center_code}</span> <span className="text-xs text-slate-500">{c.cost_center_name}</span>
                  {!c.is_active && <Badge value="INACTIVE" className="ml-1" />}</td>
                <td className="px-3 py-1">
                  <Select options={[{ value: "", label: "No access" }, ...ROLES.map((r) => ({ value: r, label: label(r) }))]}
                    value={byCc[c.cost_center_id] || ""} onChange={(v) => set(c.cost_center_id, v)} />
                </td>
              </tr>
            )),
          ])}
        </tbody>
      </table>
    </div>
  );
}

export default function Users() {
  const toast = useToast();
  const { data = [], reload } = useApi("/users", []);
  const { data: ccs = [] } = useApi("/cost-centers", []);
  const [form, setForm] = useState(null);
  const ccCode = (id) => (ccs || []).find((c) => c.cost_center_id === id)?.cost_center_code || `#${id}`;
  const save = async () => {
    try {
      const body = { full_name: form.full_name, is_super_admin: form.is_super_admin, cost_center_roles: form.cost_center_roles };
      if (form.id) {
        if (form.password) body.password = form.password;
        await client.put(`/users/${form.id}`, { ...body, is_active: form.is_active });
      } else await client.post("/users", { ...body, username: form.username, password: form.password });
      toast.ok(`User ${form.username} saved`);
      setForm(null);
      reload();
    } catch (e) {
      toast.error(apiErrorMessage(e));
    }
  };
  return (
    <>
      <PageHeader title="Users" subtitle="Logins and their role in each cost center"
        actions={<Button icon={Plus} onClick={() => setForm({ username: "", full_name: "", password: "", is_super_admin: false, cost_center_roles: [] })}>New user</Button>} />
      <Card padded={false}>
        <Table rowKey={(r) => r.id} rows={data || []} onRowClick={(r) => setForm({ ...r, is_super_admin: r.role === "SUPER_ADMIN", password: "" })} columns={[
          { key: "username", title: "Username", className: "font-medium" }, { key: "full_name", title: "Name" },
          { key: "roles", title: "Access", render: (r) => r.role === "SUPER_ADMIN"
            ? <span className="inline-flex items-center gap-1 text-xs font-medium text-brand-700"><ShieldCheck className="h-3.5 w-3.5" /> Super admin - all companies and cost centers</span>
            : r.cost_center_roles.length
              ? <span className="flex flex-wrap gap-1">{r.cost_center_roles.map((x) => <span key={x.cost_center_id} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px]"><b>{ccCode(x.cost_center_id)}</b> {label(x.role)}</span>)}</span>
              : <span className="text-xs text-slate-400">No cost center</span> },
          { key: "is_active", title: "Status", render: (r) => <Badge value={r.is_active ? "ACTIVE" : "INACTIVE"} /> },
        ]} />
      </Card>
      <Modal open={!!form} wide title={form?.id ? `Edit ${form.username}` : "New user"} onClose={() => setForm(null)} onSave={save}>
        {form && (
          <div className="grid gap-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput label="Username" required disabled={!!form.id} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
              <TextInput label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
              <TextInput label={form.id ? "New password (leave blank to keep)" : "Password"} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} hint="At least 6 characters" />
              {form.id && <Checkbox label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} className="self-end pb-2" />}
            </div>
            <Checkbox label="Super admin - manages companies, cost centers and users, and has full access everywhere" checked={form.is_super_admin} onChange={(v) => setForm({ ...form, is_super_admin: v })} />
            {!form.is_super_admin && (
              <>
                <RoleGrid costCenters={ccs || []} roles={form.cost_center_roles} onChange={(r) => setForm({ ...form, cost_center_roles: r })} />
                <ul className="text-xs text-slate-500">{ROLES.map((r) => <li key={r}><b>{label(r)}</b>: {ROLE_HELP[r]}</li>)}</ul>
              </>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
