import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowDown, ArrowLeftRight, ArrowUp, Plus, Route as RouteIcon, Save, Trash2 } from "lucide-react";
import client, { apiErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Badge, Button, Card, Empty, IconButton, Modal, PageHeader } from "../components/ui";
import { Combobox, NumberInput, Select, TextInput } from "../components/inputs";
import RouteDiagram from "../components/viz/RouteDiagram";
import { TYPE_COLOR } from "../components/viz/colors";
import { useFormKeys } from "../lib/keys";
import { focusCell, gridArrows } from "../lib/grid";
import { locOptions, useApi } from "../lib/useApi";

const DIR_COLORS = [TYPE_COLOR.PASSENGER_TRIP, "#6250d6", "#1baf7a", "#eb6834"];

function StopEditor({ direction, locs, onSaved, canEdit, color }) {
  const toast = useToast();
  const toRows = (d) => (d.stops.length ? d.stops : [{ location_id: d.start_terminal_id, distance_from_previous_km: 0 }, { location_id: d.end_terminal_id, distance_from_previous_km: null }])
    .map((s) => ({ location_id: s.location_id, distance_from_previous_km: s.distance_from_previous_km === null ? null : Number(s.distance_from_previous_km), is_pickup_dropoff_stop: s.is_pickup_dropoff_stop ?? true }));
  const [rows, setRows] = useState(() => toRows(direction));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const grid = useRef(null);
  useEffect(() => { setRows(toRows(direction)); setDirty(false); }, [direction]); // eslint-disable-line react-hooks/exhaustive-deps
  const byId = useMemo(() => Object.fromEntries((locs || []).map((l) => [l.location_id, l])), [locs]);
  const opts = locOptions(locs);
  const update = (i, patch) => { setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x))); setDirty(true); };
  const insertAt = (i) => { setRows((r) => [...r.slice(0, i), { location_id: null, distance_from_previous_km: null, is_pickup_dropoff_stop: true }, ...r.slice(i)]); setDirty(true); focusCell(grid.current, i, "loc"); };
  const remove = (i) => { setRows((r) => r.filter((_, j) => j !== i)); setDirty(true); };
  const move = (i, d) => { setRows((r) => { const n = [...r]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n; }); setDirty(true); };

  let cum = 0;
  const preview = rows.map((r, i) => {
    const d = i === 0 ? 0 : Number(r.distance_from_previous_km) || 0;
    cum += d;
    const l = byId[r.location_id];
    return { location_id: r.location_id, location_code: l?.location_code || "?", location_name: l?.location_name || "Not selected", distance_from_previous_km: d, cumulative_distance_km: cum };
  });
  const save = async () => {
    if (rows.some((r) => !r.location_id)) return toast.error("Every row needs a location");
    if (rows.slice(1).some((r) => r.distance_from_previous_km === null)) return toast.error("Enter the distance from the previous stop for every stop");
    setSaving(true);
    try {
      const { data } = await client.post(`/directions/${direction.direction_id}/stops`, {
        stops: rows.map((r, i) => ({ ...r, distance_from_previous_km: i === 0 ? 0 : r.distance_from_previous_km })),
      });
      toast.ok(`${direction.direction_code}: ${data.stops.length} stops, ${Number(data.total_distance_km)} km saved`);
      setDirty(false);
      onSaved();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };
  // Enter on the last cell of the second-to-last row inserts a stop before the end terminal
  const onLastEnter = () => insertAt(rows.length - 1);
  const keys = useFormKeys({ onSave: save, onLastEnter });
  return (
    <div className="space-y-3">
      <RouteDiagram stops={preview} startTerminalId={direction.start_terminal_id} endTerminalId={direction.end_terminal_id} color={color} />
      <div ref={grid} onKeyDown={(e) => { gridArrows(e); keys(e); }}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="w-10 px-1 py-1">#</th><th className="px-1 py-1">Stop</th><th className="w-36 px-1 py-1 text-right">From previous</th>
              <th className="w-28 px-1 py-1 text-right">Cumulative</th><th className="w-20 px-1 py-1 text-center">Pick-up</th><th className="w-24" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const terminal = i === 0 || i === rows.length - 1;
              const wrongTerminal = (i === 0 && r.location_id !== direction.start_terminal_id) || (i === rows.length - 1 && r.location_id !== direction.end_terminal_id);
              return (
                <tr key={i} className="border-t border-slate-100">
                  <td className="px-1 py-1 text-xs tabular-nums text-slate-500">{i + 1}</td>
                  <td className="px-1 py-1" data-row={i} data-col="loc">
                    <Combobox options={opts} value={r.location_id} onChange={(v) => update(i, { location_id: v })} disabled={!canEdit}
                      error={wrongTerminal ? `Must be ${i === 0 ? "start" : "end"} terminal ${byId[i === 0 ? direction.start_terminal_id : direction.end_terminal_id]?.location_name}` : null} />
                  </td>
                  <td className="px-1 py-1" data-row={i} data-col="km">
                    {i === 0 ? <div className="px-2 text-right text-xs text-slate-400">start</div> :
                      <NumberInput value={r.distance_from_previous_km} min={0} suffix="km" onChange={(v) => update(i, { distance_from_previous_km: v })} disabled={!canEdit} />}
                  </td>
                  <td className="px-1 py-1 text-right tabular-nums text-slate-600">{preview[i].cumulative_distance_km.toLocaleString("en-IN", { maximumFractionDigits: 2 })} km</td>
                  <td className="px-1 py-1 text-center" data-row={i} data-col="pick">
                    <input type="checkbox" tabIndex={terminal ? -1 : 0} disabled={!canEdit} checked={r.is_pickup_dropoff_stop} onChange={(e) => update(i, { is_pickup_dropoff_stop: e.target.checked })} className="h-4 w-4 rounded border-slate-300" />
                  </td>
                  <td className="whitespace-nowrap px-1 py-1 text-right">
                    {canEdit && (
                      <>
                        <IconButton icon={ArrowUp} title="Move up" disabled={i === 0} onClick={() => move(i, -1)} />
                        <IconButton icon={ArrowDown} title="Move down" disabled={i === rows.length - 1} onClick={() => move(i, 1)} />
                        <IconButton icon={Plus} title="Insert stop after" disabled={i === rows.length - 1} onClick={() => insertAt(i + 1)} />
                        <IconButton icon={Trash2} title="Remove" disabled={rows.length <= 2} onClick={() => remove(i)} />
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500">Enter moves across · ↑↓ between rows · Enter on the last field inserts a stop before the terminal · Ctrl+S saves</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" icon={Plus} onClick={() => insertAt(rows.length - 1)}>Add stop</Button>
            <Button size="sm" icon={Save} loading={saving} disabled={!dirty} onClick={save}>Save stops</Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function RoutesPage() {
  const { routeId } = useParams();
  const nav = useNavigate();
  const { can, canIn, isAll, ccCode } = useAuth();
  const toast = useToast();
  const { data: routes = [], reload } = useApi("/routes", []);
  const { data: locs = [] } = useApi("/locations", []);
  const [routeForm, setRouteForm] = useState(null);
  const [dirForm, setDirForm] = useState(null);
  const route = (routes || []).find((r) => String(r.route_id) === routeId) || null;
  const terminals = locOptions(locs);
  useEffect(() => {
    if (!routeId && routes?.length) nav(`/routes/${routes[0].route_id}`, { replace: true });
  }, [routeId, routes]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveRoute = async () => {
    try {
      const { data } = routeForm.route_id ? await client.put(`/routes/${routeForm.route_id}`, routeForm) : await client.post("/routes", routeForm);
      toast.ok(`Route ${data.route_code} saved`);
      setRouteForm(null);
      await reload();
      nav(`/routes/${data.route_id}`);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const saveDir = async () => {
    try {
      const { reverseOf, ...body } = dirForm;
      let d;
      if (dirForm.direction_id) d = (await client.put(`/directions/${dirForm.direction_id}`, body)).data;
      else d = (await client.post(`/routes/${route.route_id}/directions`, body)).data;
      if (reverseOf) {
        // seed the reverse stop list: same stops backwards, distances mirrored (edit them if they differ)
        const s = reverseOf.stops;
        const stops = [...s].reverse().map((x, i, arr) => ({
          location_id: x.location_id, is_pickup_dropoff_stop: x.is_pickup_dropoff_stop,
          distance_from_previous_km: i === 0 ? 0 : Number(s[s.length - i].distance_from_previous_km),
        }));
        if (stops.length >= 2) await client.post(`/directions/${d.direction_id}/stops`, { stops });
      }
      toast.ok(`Direction ${d.direction_code} saved`);
      setDirForm(null);
      reload();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const deleteRoute = async () => {
    if (!window.confirm(`Delete route ${route.route_code} with its directions and stops?`)) return;
    try {
      await client.delete(`/routes/${route.route_id}`);
      toast.ok(`Route ${route.route_code} deleted`);
      await reload();
      nav("/routes", { replace: true });
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };
  const reverse = (d) => setDirForm({
    direction_code: d.direction_code === "UPSTREAM" ? "DOWNSTREAM" : d.direction_code === "DOWNSTREAM" ? "UPSTREAM" : `${d.direction_code}-R`,
    direction_name: `${d.end_terminal_name} to ${d.start_terminal_name}`, start_terminal_id: d.end_terminal_id, end_terminal_id: d.start_terminal_id, is_active: true, reverseOf: d,
  });
  return (
    <>
      <PageHeader title="Routes & directions" subtitle="Each direction has its own ordered stops and distances"
        actions={can("SCHEDULER") && <Button icon={Plus} onClick={() => setRouteForm({ route_code: "", route_name: "", description: "", status: "ACTIVE" })}>New route</Button>} />
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card title="Routes" padded={false}>
          {(routes || []).length === 0 && <Empty icon={RouteIcon} title="No routes yet" />}
          <ul>
            {(routes || []).map((r) => (
              <li key={r.route_id}>
                <button onClick={() => nav(`/routes/${r.route_id}`)} className={`w-full border-b border-slate-100 px-4 py-2.5 text-left ${String(r.route_id) === routeId ? "bg-brand-50" : "hover:bg-slate-50"}`}>
                  <p className="flex items-center justify-between text-sm font-medium text-ink">{r.route_code} {r.status !== "ACTIVE" && <Badge value={r.status} />}</p>
                  <p className="truncate text-xs text-slate-500">{isAll && <b className="mr-1 font-medium text-slate-600">{ccCode(r.cost_center_id)}</b>}{r.route_name}</p>
                  <p className="mt-1 flex gap-1">{r.directions.map((d, i) => (
                    <span key={d.direction_id} className="rounded px-1.5 py-0.5 text-[10px] font-medium text-white" style={{ background: DIR_COLORS[i % 4] }}>{d.direction_code} · {Number(d.total_distance_km)} km</span>
                  ))}</p>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        {route ? (
          <div className="space-y-4">
            <Card title={<div><h2 className="text-sm font-semibold">{route.route_code} · {route.route_name}</h2>{route.description && <p className="text-xs text-slate-500">{route.description}</p>}</div>}
              actions={canIn(route.cost_center_id, "SCHEDULER") && (
                <>
                  <Button size="sm" variant="secondary" onClick={() => setRouteForm({ ...route })}>Edit route</Button>
                  {!route.in_use && <Button size="sm" variant="ghost" icon={Trash2} onClick={deleteRoute}>Delete route</Button>}
                  <Button size="sm" icon={Plus} onClick={() => setDirForm({ direction_code: route.directions.length ? "DOWNSTREAM" : "UPSTREAM", direction_name: "", start_terminal_id: null, end_terminal_id: null, is_active: true })}>Add direction</Button>
                </>
              )}>
              {route.directions.length === 0 ? <Empty icon={RouteIcon} title="Add an upstream direction to start" /> : (
                <div className="space-y-4">
                  {route.directions.map((d, i) => (
                    <RouteDiagram key={d.direction_id} title={`${d.direction_code} · ${d.direction_name}`} stops={d.stops} color={DIR_COLORS[i % 4]} />
                  ))}
                </div>
              )}
            </Card>
            {route.directions.map((d, i) => (
              <Card key={d.direction_id}
                title={<div className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm" style={{ background: DIR_COLORS[i % 4] }} /><h2 className="text-sm font-semibold">{d.direction_code}</h2><span className="text-xs text-slate-500">{d.start_terminal_name} → {d.end_terminal_name}</span>{!d.is_active && <Badge value="INACTIVE" />}</div>}
                actions={canIn(route.cost_center_id, "SCHEDULER") && (
                  <>
                    {d.stops.length >= 2 && route.directions.every((x) => x.start_terminal_id !== d.end_terminal_id || x.end_terminal_id !== d.start_terminal_id) &&
                      <Button size="sm" variant="secondary" icon={ArrowLeftRight} onClick={() => reverse(d)}>Create reverse direction</Button>}
                    <Button size="sm" variant="ghost" onClick={() => setDirForm({ ...d })}>Edit</Button>
                  </>
                )}>
                <StopEditor direction={d} locs={locs} onSaved={reload} canEdit={canIn(route.cost_center_id, "SCHEDULER")} color={DIR_COLORS[i % 4]} />
              </Card>
            ))}
          </div>
        ) : <Card><Empty icon={RouteIcon} title="Select or create a route" /></Card>}
      </div>
      <Modal open={!!routeForm} title={routeForm?.route_id ? "Edit route" : "New route"} onClose={() => setRouteForm(null)} onSave={saveRoute}>
        {routeForm && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Route code" required value={routeForm.route_code} onChange={(e) => setRouteForm({ ...routeForm, route_code: e.target.value.toUpperCase() })} />
            <Select label="Status" options={[{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }]} value={routeForm.status} onChange={(v) => setRouteForm({ ...routeForm, status: v })} />
            <TextInput label="Route name" required className="col-span-2" value={routeForm.route_name} onChange={(e) => setRouteForm({ ...routeForm, route_name: e.target.value })} />
            <TextInput label="Description" className="col-span-2" value={routeForm.description || ""} onChange={(e) => setRouteForm({ ...routeForm, description: e.target.value })} />
          </div>
        )}
      </Modal>
      <Modal open={!!dirForm} title={dirForm?.direction_id ? "Edit direction" : dirForm?.reverseOf ? "Create reverse direction" : "New direction"} onClose={() => setDirForm(null)} onSave={saveDir}>
        {dirForm && (
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Direction code" required value={dirForm.direction_code} onChange={(e) => setDirForm({ ...dirForm, direction_code: e.target.value.toUpperCase() })} hint="e.g. UPSTREAM / DOWNSTREAM" />
            <TextInput label="Display name" required value={dirForm.direction_name} onChange={(e) => setDirForm({ ...dirForm, direction_name: e.target.value })} />
            <Combobox label="Start terminal" required options={terminals} value={dirForm.start_terminal_id} disabled={!!dirForm.direction_id && dirForm.stops?.length > 0} onChange={(v) => setDirForm({ ...dirForm, start_terminal_id: v })} />
            <Combobox label="End terminal" required options={terminals} value={dirForm.end_terminal_id} disabled={!!dirForm.direction_id && dirForm.stops?.length > 0} onChange={(v) => setDirForm({ ...dirForm, end_terminal_id: v })} />
            {dirForm.reverseOf && <p className="col-span-2 text-xs text-slate-500">The stop list is copied in reverse with mirrored distances. Adjust the stops and distances afterwards if the reverse journey differs.</p>}
          </div>
        )}
      </Modal>
    </>
  );
}
