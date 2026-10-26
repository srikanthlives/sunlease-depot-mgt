import { Card, PageHeader, Table } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { fmtDate } from "../lib/format";
import { useApi } from "../lib/useApi";

export default function AuditLog() {
  const { ccCode } = useAuth();
  const { data = [] } = useApi("/audit-logs?limit=300", []);
  return (
    <>
      <PageHeader title="Audit log" subtitle="Who created, changed and published what (latest 300)" />
      <Card padded={false}>
        <Table rowKey={(r) => r.id} rows={data || []} columns={[
          { key: "at", title: "When (UTC)", className: "whitespace-nowrap tabular-nums", render: (r) => `${fmtDate(r.at.slice(0, 10))} ${r.at.slice(11, 16)}` },
          { key: "cc", title: "Cost center", render: (r) => (r.cost_center_id ? ccCode(r.cost_center_id) : "—") },
          { key: "username", title: "User" }, { key: "action", title: "Action", className: "font-medium" },
          { key: "entity", title: "Record", render: (r) => `${r.entity_type}${r.entity_id ? ` #${r.entity_id}` : ""}` },
          { key: "detail", title: "Detail", render: (r) => <span className="line-clamp-2 break-all text-xs text-slate-500">{r.detail}</span> },
        ]} />
      </Card>
    </>
  );
}
