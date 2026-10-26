import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Button, Card, PageHeader, Spinner } from "../components/ui";
import { Checkbox, NumberInput } from "../components/inputs";
import { useFormKeys } from "../lib/keys";
import { label } from "../lib/format";
import { useApi } from "../lib/useApi";

export default function SettingsPage() {
  const { can, isAll, current } = useAuth();
  const toast = useToast();
  const { data } = useApi(isAll ? null : "/settings");
  const [v, setV] = useState(null);
  useEffect(() => { if (data) setV(data.values); }, [data]);
  const keys = useFormKeys({ onSave: () => save() });
  if (isAll) {
    return (
      <>
        <PageHeader title="Validation settings" subtitle="Set per cost center" />
        <Card className="max-w-xl"><p className="text-sm text-slate-600">Validation settings belong to one cost center. Pick a cost center in the top bar to see or change them.</p></Card>
      </>
    );
  }
  if (!v) return <Spinner />;
  const save = async () => {
    try {
      await client.put("/settings", { values: v });
      toast.ok("Validation settings saved");
    } catch (e) {
      toast.error(apiErrorMessage(e));
    }
  };
  const d = data.descriptions;
  const admin = can("ADMIN");
  return (
    <>
      <PageHeader title="Validation settings" subtitle={`${current ? `${current.cost_center_code} · ${current.cost_center_name} - ` : ""}which planned readings are mandatory, and how strict the checks are`} />
      <Card className="max-w-xl">
        <fieldset disabled={!admin} className="space-y-4" onKeyDown={keys}>
          <Checkbox label={d.require_stop_soc} checked={v.require_stop_soc === "true"} onChange={(x) => setV({ ...v, require_stop_soc: String(x) })} />
          <NumberInput label={d.distance_tolerance_pct} suffix="%" min={0} max={100} value={Number(v.distance_tolerance_pct)} onChange={(x) => setV({ ...v, distance_tolerance_pct: String(x ?? 0) })} className="w-64" />
          <NumberInput label={d.gap_warn_minutes} suffix="min" min={0} value={Number(v.gap_warn_minutes)} onChange={(x) => setV({ ...v, gap_warn_minutes: String(x ?? 0) })} className="w-64" />
          <p className="border-t border-slate-100 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Trip sheets</p>
          <p className="text-xs text-slate-500">The language printed on trip sheets is set on the company and the cost center, under <b>Organisation</b>.</p>
          <NumberInput label={d.odometer_tolerance_pct} suffix="%" min={0} max={100} value={Number(v.odometer_tolerance_pct)} onChange={(x) => setV({ ...v, odometer_tolerance_pct: String(x ?? 0) })} className="w-64" />
          <div>
            <p className="mb-1 text-sm text-ink">{d.bill_lost_km_attributable_to}</p>
            {["OPERATOR", "CLIENT", "EXTERNAL"].map((a) => {
              const list = (v.bill_lost_km_attributable_to || "").split(",").filter(Boolean);
              return <Checkbox key={a} label={label(a)} checked={list.includes(a)}
                onChange={(on) => setV({ ...v, bill_lost_km_attributable_to: (on ? [...list, a] : list.filter((x) => x !== a)).join(",") })} />;
            })}
            <p className="mt-1 text-xs text-slate-500">Billing is planned km minus km lost to cancelled or cut-short runs; losses attributable to a ticked party are not deducted.</p>
          </div>
          {admin ? <Button icon={Save} onClick={save}>Save</Button> : <p className="text-xs text-slate-500">Only an admin of this cost center can change these.</p>}
        </fieldset>
      </Card>
    </>
  );
}
