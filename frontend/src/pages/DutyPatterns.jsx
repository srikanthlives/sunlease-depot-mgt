import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Pencil, Plus, Repeat2, Trash2, X } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, IconButton, Modal, PageHeader, Table } from "../components/ui";
import { Combobox, NumberInput, Select, TextInput } from "../components/inputs";
import { label } from "../lib/format";
import { useApi } from "../lib/useApi";

const blank = { pattern_code: "", pattern_name: "", cycle_days: 7, is_active: true };

/**
 * Duty patterns: a repeating crew cycle that generates a draft roster.
 *
 * The cycle has a row per day; each day carries one duty or is an off day. The members are a
 * line of crew, and each starts the cycle a day further along - so over a full cycle everybody
 * works every duty and takes every off day, the way a depot's turn roster does on paper.
 */
export default function DutyPatterns() {
  const { can } = useAuth();
  const toast = useToast();
  const { data: patterns = [], reload } = useApi("/duty-patterns", []);
  const { data: schedules = [] } = useApi("/schedules", []);
  const { data: employees = [] } = useApi("/employees", []);
  const [edit, setEdit] = useState(null);
  const [open, setOpen] = useState(null);     // the pattern whose cycle is being edited

  const pattern = useMemo(() => (patterns || []).find((p) => p.pattern_id === open?.pattern_id) || open,
    [patterns, open]);

  const scheduleOptions = useMemo(() => (schedules || [])
    .filter((s) => s.status === "PUBLISHED")
    .map((s) => ({ value: s.schedule_id, label: s.schedule_code, sub: s.schedule_name })), [schedules]);
  const crewOptions = useMemo(() => (employees || [])
    .filter((e) => e.status === "ACTIVE" && e.staff_type !== "DEPOT_STAFF")
    .map((e) => ({ value: e.employee_id, label: `${e.employee_number} - ${e.full_name}`,
                   sub: label(e.staff_type) })), [employees]);

  const save = async () => {
    try {
      if (edit.pattern_id) await client.put(`/duty-patterns/${edit.pattern_id}`, edit);
      else await client.post("/duty-patterns", edit);
      toast.ok(`Pattern ${edit.pattern_code} saved`);
      setEdit(null);
      reload();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const remove = async (p) => {
    if (!window.confirm(`Delete pattern ${p.pattern_code}? Rosters already generated from it are not affected.`)) return;
    try {
      await client.delete(`/duty-patterns/${p.pattern_id}`);
      toast.ok("Deleted");
      if (open?.pattern_id === p.pattern_id) setOpen(null);
      reload();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  /** The cycle is saved whole: one duty per day, or an off day. */
  const saveSlots = async (slots) => {
    try {
      const { data } = await client.put(`/duty-patterns/${pattern.pattern_id}/slots`, { slots });
      setOpen(data);
      reload();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };
  const setDay = (cycle_day, changes) => {
    const slots = [];
    for (let d = 0; d < pattern.cycle_days; d++) {
      const current = pattern.slots.find((s) => s.cycle_day === d);
      const next = d === cycle_day ? { ...current, cycle_day: d, ...changes } : current;
      if (next && next.schedule_id) {
        slots.push({ cycle_day: d, schedule_id: next.schedule_id,
                     shift_number: next.shift_number ?? null, crew_role: next.crew_role || "DRIVER" });
      }
    }
    saveSlots(slots);
  };

  const saveMembers = async (ids) => {
    try {
      const { data } = await client.put(`/duty-patterns/${pattern.pattern_id}/members`,
        { employee_ids: ids });
      setOpen(data);
      reload();
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };
  const memberIds = (pattern?.members || []).map((m) => m.employee_id);
  const moveMember = (i, by) => {
    const ids = [...memberIds];
    const j = i + by;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    saveMembers(ids);
  };

  return (
    <>
      <PageHeader title="Duty patterns"
        subtitle="A repeating crew cycle, used to generate a draft roster"
        actions={can("SCHEDULER") && <Button icon={Plus} onClick={() => setEdit({ ...blank })}>New pattern</Button>} />

      <Card padded={false} title={`${(patterns || []).length} patterns`}>
        <Table rowKey={(p) => p.pattern_id} rows={patterns || []} onRowClick={(p) => setOpen(p)} columns={[
          { key: "pattern_code", title: "Code", className: "font-medium" },
          { key: "pattern_name", title: "Name", render: (p) => p.pattern_name || "—" },
          { key: "cycle_days", title: "Cycle", render: (p) => `${p.cycle_days} days` },
          { key: "duties", title: "Duties in cycle", render: (p) => `${p.slots.length} duty, ${p.cycle_days - p.slots.length} off` },
          { key: "members", title: "Crew in line", render: (p) => p.members.length },
          { key: "is_active", title: "Status", render: (p) => <Badge value={p.is_active ? "ACTIVE" : "INACTIVE"} /> },
          { key: "x", title: "", className: "w-20 text-right", render: (p) => can("SCHEDULER") && (
            <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
              <IconButton icon={Pencil} title="Rename" onClick={() => setEdit({ ...p })} />
              <IconButton icon={Trash2} title="Delete" onClick={() => remove(p)} />
            </span>
          ) },
        ]} empty={<span className="inline-flex items-center gap-2"><Repeat2 className="h-4 w-4" /> No patterns yet</span>} />
      </Card>

      {pattern && (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <Card title={`${pattern.pattern_code}: the cycle`}
            actions={<button className="text-xs text-slate-500 hover:underline" onClick={() => setOpen(null)}>Close</button>}>
            <p className="mb-2 text-xs text-slate-500">
              One duty per cycle day, or leave it empty for an off day. A second duty on the same day
              would put one person on two buses, so that needs a second pattern.
            </p>
            <div className="space-y-2">
              {Array.from({ length: pattern.cycle_days }, (_, d) => {
                const slot = pattern.slots.find((s) => s.cycle_day === d);
                return (
                  <div key={d} className="flex items-end gap-2">
                    <div className="w-20 pb-2 text-xs text-slate-500">Day {d + 1}</div>
                    <Combobox className="flex-1" options={scheduleOptions} value={slot?.schedule_id ?? null}
                      placeholder="Off day" disabled={!can("SCHEDULER")}
                      onChange={(v) => setDay(d, { schedule_id: v })} />
                    <Select className="w-32" options={[{ value: "DRIVER", label: "Driver" },
                                                       { value: "CONDUCTOR", label: "Conductor" }]}
                      value={slot?.crew_role || "DRIVER"} disabled={!can("SCHEDULER") || !slot?.schedule_id}
                      onChange={(v) => setDay(d, { crew_role: v })} />
                    <NumberInput className="w-20" integer min={1} placeholder="Shift"
                      value={slot?.shift_number ?? null} disabled={!can("SCHEDULER") || !slot?.schedule_id}
                      onChange={(v) => setDay(d, { shift_number: v })} />
                    {slot?.schedule_id && can("SCHEDULER") && (
                      <IconButton icon={X} title="Make this an off day"
                        onClick={() => setDay(d, { schedule_id: null })} />
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          <Card title={`${pattern.pattern_code}: the line of crew`}>
            <p className="mb-2 text-xs text-slate-500">
              Rotation order. The first person starts on day 1 of the cycle, the second on day 2, and
              so on - so the line cannot be longer than the {pattern.cycle_days}-day cycle.
            </p>
            <ol className="mb-3 space-y-1">
              {(pattern.members || []).map((m, i) => (
                <li key={m.member_id} className="flex items-center gap-2 text-sm">
                  <span className="w-6 text-xs text-slate-400">{i + 1}.</span>
                  <span className="flex-1">{m.employee_name}
                    <span className="ml-1 font-mono text-xs text-slate-400">{m.employee_number}</span></span>
                  {can("SCHEDULER") && (
                    <span className="inline-flex gap-1">
                      <IconButton icon={ArrowUp} title="Earlier in the line" onClick={() => moveMember(i, -1)} />
                      <IconButton icon={ArrowDown} title="Later in the line" onClick={() => moveMember(i, 1)} />
                      <IconButton icon={X} title="Remove from the line"
                        onClick={() => saveMembers(memberIds.filter((id) => id !== m.employee_id))} />
                    </span>
                  )}
                </li>
              ))}
              {(pattern.members || []).length === 0 && <li className="text-sm text-slate-400">Nobody in the line yet</li>}
            </ol>
            {can("SCHEDULER") && (
              <Combobox label="Add to the line" options={crewOptions.filter((o) => !memberIds.includes(o.value))}
                value={null} onChange={(v) => v && saveMembers([...memberIds, v])} />
            )}
          </Card>
        </div>
      )}

      <p className="mt-2 text-xs text-slate-500">
        To use a pattern, open a draft roster and choose <b>Generate</b>. Generated cells are marked
        so later hand edits stay visible, and re-generating keeps them unless you ask to overwrite.
      </p>

      <Modal open={!!edit} title={edit?.pattern_id ? `Edit ${edit.pattern_code}` : "New duty pattern"}
        onClose={() => setEdit(null)} onSave={save}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Code" required autoFocus value={edit.pattern_code}
              onChange={(e) => setEdit({ ...edit, pattern_code: e.target.value.toUpperCase().replace(/\s+/g, "-") })} />
            <NumberInput label="Days in the cycle" integer min={1} max={90} value={edit.cycle_days}
              onChange={(v) => setEdit({ ...edit, cycle_days: v })} />
            <TextInput label="Name" className="col-span-2" value={edit.pattern_name || ""}
              onChange={(e) => setEdit({ ...edit, pattern_name: e.target.value })} />
            <p className="col-span-2 text-xs text-slate-500">
              A weekly turn with one rest day is a 7-day cycle with six duties and one empty day.
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}
