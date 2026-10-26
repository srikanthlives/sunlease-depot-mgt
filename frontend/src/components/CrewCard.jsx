import { useEffect, useState } from "react";
import { Plus, Save, Trash2, Users2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import { Button, Card, IconButton } from "./ui";
import { Checkbox, Combobox, Select, TextInput, TimeInput } from "./inputs";
import { fmtDuration, fmtRel, label, options, relMin } from "../lib/format";
import { locOptions } from "../lib/useApi";

const fromVersion = (v) => ({
  crew_mode: v.crew_mode || "SINGLE", conductor_required: !!v.conductor_required,
  shifts: (v.shifts || []).map(({ shift_name, start_day_offset, start_time, end_day_offset, end_time, change_location_id }) =>
    ({ shift_name, start_day_offset, start_time, end_day_offset, end_time, change_location_id })),
});

/** Crew pattern of a schedule version: drives how trip sheets lay out drivers and conductors. */
export default function CrewCard({ version, canEdit, locs, onSaved }) {
  const toast = useToast();
  const [form, setForm] = useState(() => fromVersion(version));
  const [saving, setSaving] = useState(false);
  useEffect(() => { setForm(fromVersion(version)); }, [version.schedule_version_id, version.crew_mode, version.shifts?.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(form) !== JSON.stringify(fromVersion(version));
  const setShift = (i, patch) => setForm((f) => ({ ...f, shifts: f.shifts.map((s, j) => (j === i ? { ...s, ...patch } : s)) }));
  const addShift = () => setForm((f) => {
    const last = f.shifts[f.shifts.length - 1];
    const name = String.fromCharCode(65 + f.shifts.length);
    return { ...f, shifts: [...f.shifts, last
      ? { shift_name: name, start_day_offset: last.end_day_offset, start_time: last.end_time, end_day_offset: last.end_day_offset, end_time: null, change_location_id: last.change_location_id }
      : { shift_name: name, start_day_offset: 0, start_time: null, end_day_offset: 0, end_time: null, change_location_id: null }] };
  });
  const save = async () => {
    if (form.crew_mode === "SHIFTS" && form.shifts.some((s) => !s.shift_name || !s.start_time || !s.end_time)) {
      toast.error("Every shift needs a name, start and end");
      return;
    }
    setSaving(true);
    try {
      const { data } = await client.put(`/schedule-versions/${version.schedule_version_id}/crew`, form);
      toast.ok("Crew pattern saved");
      onSaved(data);
    } catch (e) {
      toast.error(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  const ro = !canEdit;
  return (
    <Card title={<span className="flex items-center gap-2"><Users2 className="h-4 w-4 text-slate-400" /><h2 className="text-sm font-semibold">Crew</h2>
      <span className="text-xs font-normal text-slate-500">how trip sheets lay out drivers{form.conductor_required ? " and conductors" : ""}</span></span>}
      actions={canEdit && <Button size="sm" icon={Save} loading={saving} disabled={!dirty} onClick={save}>Save crew</Button>}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-4">
          <Select label="Pattern" options={options(["SINGLE", "SHIFTS"])} value={form.crew_mode} disabled={ro} className="w-56"
            onChange={(v) => setForm((f) => ({ ...f, crew_mode: v, shifts: v === "SHIFTS" && !f.shifts.length ? [] : f.shifts }))} />
          <Checkbox label="Conductor required" checked={form.conductor_required} onChange={(v) => !ro && setForm((f) => ({ ...f, conductor_required: v }))} className="pb-2" />
        </div>
        {form.crew_mode === "SHIFTS" && (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-2 py-1.5">Shift</th><th className="px-2 py-1.5">Starts</th><th className="px-2 py-1.5">Ends</th>
                  <th className="px-2 py-1.5">Length</th><th className="px-2 py-1.5">Crew change at</th><th className="w-8" /></tr>
              </thead>
              <tbody>
                {form.shifts.map((s, i) => {
                  const a = relMin(s.start_day_offset, s.start_time), b = relMin(s.end_day_offset, s.end_time);
                  return (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-2 py-1"><TextInput value={s.shift_name} disabled={ro} onChange={(e) => setShift(i, { shift_name: e.target.value })} className="w-28" /></td>
                      <td className="px-2 py-1"><TimeInput value={s.start_time} offset={s.start_day_offset} disabled={ro}
                        onChange={(v) => setShift(i, { start_time: v })} onOffsetChange={(v) => setShift(i, { start_day_offset: v })} /></td>
                      <td className="px-2 py-1"><TimeInput value={s.end_time} offset={s.end_day_offset} disabled={ro}
                        onChange={(v) => setShift(i, { end_time: v })} onOffsetChange={(v) => setShift(i, { end_day_offset: v })} /></td>
                      <td className="px-2 py-1 text-xs tabular-nums text-slate-500">{a !== null && b !== null ? (b > a ? `${fmtDuration(b - a)} · ${fmtRel(a)} → ${fmtRel(b)}` : <span className="text-danger">end before start</span>) : ""}</td>
                      <td className="px-2 py-1"><Combobox options={locOptions(locs)} value={s.change_location_id} disabled={ro} placeholder="Optional"
                        onChange={(v) => setShift(i, { change_location_id: v })} className="w-48" /></td>
                      <td className="px-1">{!ro && <IconButton icon={Trash2} title="Remove shift" onClick={() => setForm((f) => ({ ...f, shifts: f.shifts.filter((_, j) => j !== i) }))} />}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!ro && <div className="border-t border-slate-100 px-2 py-1.5"><Button size="sm" variant="secondary" icon={Plus} onClick={addShift}>Add shift</Button></div>}
          </div>
        )}
        <p className="text-xs text-slate-500">
          {form.crew_mode === "SHIFTS"
            ? "Each shift gets its own driver" + (form.conductor_required ? " and conductor" : "") + " on the trip sheet. Shifts must not overlap; a gap or uncovered driving gives a warning."
            : `One ${label("DRIVER").toLowerCase()}${form.conductor_required ? " and one conductor" : ""} for the whole day. A driver change during the day is recorded on the trip sheet.`}
          {" "}The pattern is part of the version, so it is locked once published.
        </p>
      </div>
    </Card>
  );
}
