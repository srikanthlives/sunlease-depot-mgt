import { useState } from "react";
import { Building2, Layers, Plus, Trash2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Empty, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Checkbox, Select, TextInput } from "../components/inputs";
import { LANGUAGES } from "../lib/i18n";
import { useApi } from "../lib/useApi";

// what the printed trip sheets carry alongside English
const LANG_OPTIONS = Object.entries(LANGUAGES).map(([value, l]) => ({ value, label: value ? `English + ${l}` : l }));

export default function Organisation() {
  const toast = useToast();
  const auth = useAuth();
  const { data: companies = [], reload: reloadCo } = useApi("/companies", []);
  const { data: ccs = [], reload: reloadCc } = useApi("/cost-centers", []);
  const [co, setCo] = useState(null);
  const [cc, setCc] = useState(null);
  const refresh = async () => {
    await Promise.all([reloadCo(), reloadCc()]);
    await auth.refresh(); // new or renamed cost centers show in the switcher straight away
  };
  const run = async (fn, ok) => {
    try {
      await fn();
      toast.ok(ok);
      await refresh();
      return true;
    } catch (e) {
      toast.error(apiErrorMessage(e));
      return false;
    }
  };
  // the company's own choice, to show in the "same as the company" option
  const companyLang = (row) => {
    const code = companies.find((c) => c.company_id === Number(row.company_id))?.print_language;
    return code === undefined ? "" : LANGUAGES[code] || LANGUAGES[""];
  };
  const saveCo = async () => {
    const { company_id, company_code, company_name, print_language, is_active } = co;
    const body = { company_code, company_name, print_language: print_language ?? "te", is_active };
    if (await run(() => (company_id ? client.put(`/companies/${company_id}`, body) : client.post("/companies", body)), `Company ${company_code} saved`)) setCo(null);
  };
  const saveCc = async () => {
    const { cost_center_id, company_id, cost_center_code, cost_center_name, print_language, is_active } = cc;
    const body = { company_id: Number(company_id), cost_center_code, cost_center_name,
                   print_language: print_language === "__company" ? null : print_language, is_active };
    if (await run(() => (cost_center_id ? client.put(`/cost-centers/${cost_center_id}`, body) : client.post("/cost-centers", body)), `Cost center ${cost_center_code} saved`)) setCc(null);
  };
  const removeCo = (c) => window.confirm(`Delete company ${c.company_code}?`) && run(() => client.delete(`/companies/${c.company_id}`), "Company deleted");
  const removeCc = (c) => window.confirm(`Delete cost center ${c.cost_center_code}?`) && run(() => client.delete(`/cost-centers/${c.cost_center_id}`), "Cost center deleted");
  const coOptions = (companies || []).map((c) => ({ value: c.company_id, label: `${c.company_code} · ${c.company_name}` }));

  return (
    <>
      <PageHeader title="Organisation" subtitle="Companies and their cost centers. Buses, routes, schedules and staff belong to a cost center; locations are shared across a company." />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={`${(companies || []).length} companies`} padded={false}
          actions={<Button size="sm" icon={Plus} onClick={() => setCo({ company_code: "", company_name: "", is_active: true })}>New company</Button>}>
          {(companies || []).length === 0 ? <Empty icon={Building2} title="No companies yet" /> : (
            <Table rowKey={(r) => r.company_id} rows={companies} onRowClick={(r) => setCo({ ...r })} columns={[
              { key: "company_code", title: "Code", className: "font-medium" }, { key: "company_name", title: "Name" },
              { key: "cost_center_count", title: "Cost centers", className: "tabular-nums" },
              { key: "is_active", title: "Status", render: (r) => <Badge value={r.is_active ? "ACTIVE" : "INACTIVE"} /> },
              { key: "x", title: "", className: "w-10 text-right", render: (r) => r.cost_center_count === 0 && (
                <span onClick={(e) => e.stopPropagation()}><IconButton icon={Trash2} title="Delete (no cost centers or locations)" onClick={() => removeCo(r)} /></span>) },
            ]} />
          )}
        </Card>
        <Card title={`${(ccs || []).length} cost centers`} padded={false}
          actions={<Button size="sm" icon={Plus} disabled={!(companies || []).length} onClick={() => setCc({ company_id: companies[0]?.company_id, cost_center_code: "", cost_center_name: "", is_active: true })}>New cost center</Button>}>
          {(ccs || []).length === 0 ? <Empty icon={Layers} title="No cost centers yet">Create a company first, then its cost centers.</Empty> : (
            <Table rowKey={(r) => r.cost_center_id} rows={ccs} onRowClick={(r) => setCc({ ...r })} columns={[
              { key: "cost_center_code", title: "Code", className: "font-medium" }, { key: "cost_center_name", title: "Name" },
              { key: "company_name", title: "Company" },
              { key: "user_count", title: "Users", className: "tabular-nums" },
              { key: "is_active", title: "Status", render: (r) => <Badge value={r.is_active ? "ACTIVE" : "INACTIVE"} /> },
              { key: "x", title: "", className: "w-10 text-right", render: (r) => (
                <span onClick={(e) => e.stopPropagation()}><IconButton icon={Trash2} title="Delete (only if it has no data)" onClick={() => removeCc(r)} /></span>) },
            ]} />
          )}
        </Card>
      </div>
      <p className="mt-3 text-xs text-slate-500">Give users a role in each cost center under <b>Users</b>. Deactivating a cost center hides it from everyone's switcher; its data is kept.</p>

      <Modal open={!!co} title={co?.company_id ? `Edit ${co.company_code}` : "New company"} onClose={() => setCo(null)} onSave={saveCo}>
        {co && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Code" required value={co.company_code} onChange={(e) => setCo({ ...co, company_code: e.target.value.toUpperCase() })} />
            <TextInput label="Name" required value={co.company_name} onChange={(e) => setCo({ ...co, company_name: e.target.value })} />
            <Select label="Trip sheet language" options={LANG_OPTIONS} value={co.print_language ?? "te"}
              hint="Printed alongside English on this company's trip sheets"
              onChange={(v) => setCo({ ...co, print_language: v ?? "" })} className="col-span-2" />
            <Checkbox label="Active" checked={co.is_active} onChange={(v) => setCo({ ...co, is_active: v })} className="col-span-2" />
          </div>
        )}
      </Modal>
      <Modal open={!!cc} title={cc?.cost_center_id ? `Edit ${cc.cost_center_code}` : "New cost center"} onClose={() => setCc(null)} onSave={saveCc}>
        {cc && (
          <div className="grid grid-cols-2 gap-3">
            <Select label="Company" required options={coOptions} value={cc.company_id} disabled={!!cc.cost_center_id}
              onChange={(v) => setCc({ ...cc, company_id: v })} className="col-span-2" />
            <TextInput label="Code" required value={cc.cost_center_code} onChange={(e) => setCc({ ...cc, cost_center_code: e.target.value.toUpperCase() })} />
            <TextInput label="Name" required value={cc.cost_center_name} onChange={(e) => setCc({ ...cc, cost_center_name: e.target.value })} />
            <Select label="Trip sheet language"
              options={[{ value: "__company", label: `Same as the company${companyLang(cc) ? ` (${companyLang(cc)})` : ""}` }, ...LANG_OPTIONS]}
              value={cc.print_language ?? "__company"} hint="Set this only where this depot prints in another language"
              onChange={(v) => setCc({ ...cc, print_language: v ?? "__company" })} className="col-span-2" />
            <Checkbox label="Active" checked={cc.is_active} onChange={(v) => setCc({ ...cc, is_active: v })} className="col-span-2" />
            {cc.cost_center_id && <p className="col-span-2 text-xs text-slate-500">A cost center stays in its company, because its routes and buses use that company's locations.</p>}
          </div>
        )}
      </Modal>
    </>
  );
}
