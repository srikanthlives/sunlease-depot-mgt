import { Fragment } from "react";
import { useSearchParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { Button, Spinner } from "../components/ui";
import { fmtDateLong, fmtDuration } from "../lib/format";
import { english, reasonLocal, regional } from "../lib/i18n";
import { useApi } from "../lib/useApi";

// OCR-ready trip sheet, A4 portrait, laid out to fit as many runs as possible on one page. Every handwritten value
// gets one box per character, sized in millimetres so the printout is true to size. Each run is an info line with its
// boxes on the row below; layovers and halts are one-line references (the office fills them). Only the arrival has a
// day box (0 / 1); the departure's day is worked out from it.
const BOX_W = "4.2mm";
const BOX_H = "5.5mm";
const SHEET_W = "200mm";

/** English label with the regional language underneath. */
function L({ k, lang, small }) {
  const r = regional(k, lang);
  return (
    <span className="leading-tight">
      <span className="block">{english(k)}</span>
      {r && <span className={`block font-normal text-slate-600 ${small ? "text-[6pt]" : "text-[7pt]"}`}>{r}</span>}
    </span>
  );
}

/** n character boxes; `marks` puts a printed separator after a box index, e.g. {1: ":"} for HH:MM. */
function Comb({ n, marks = {} }) {
  return (
    <span className="inline-flex items-end align-middle">
      {Array.from({ length: n }, (_, i) => (
        <span key={i} className="inline-flex items-end">
          <span style={{ width: BOX_W, height: BOX_H }} className={`inline-block border border-ink ${i === n - 1 || marks[i] ? "" : "border-r-0"}`} />
          {marks[i] && <span className="px-[0.3mm] text-[9pt] font-bold leading-none">{marks[i]}</span>}
        </span>
      ))}
    </span>
  );
}
const Time = () => <Comb n={4} marks={{ 1: ":" }} />;
/** "Name (regional name)" when the location has one. */
const place = (name, local) => (local ? `${name} (${local})` : name);
/** "Empty run / ఖాళీ ప్రయాణం" -> "Empty run": the one-line run label has no room for both. */
const englishOnly = (text) => String(text).split(" / ")[0];
const TICKS = ["ran", "cut", "notRun"];
const TickBox = ({ hidden }) => <span style={{ width: "3.8mm", height: "3.8mm" }} className={`inline-block ${hidden ? "" : "border border-ink"}`} />;
/** Header for the status column: the three tick labels, aligned over the boxes in each row. */
const TickHead = () => (
  <span className="grid grid-cols-3 text-center text-[5pt] font-normal leading-none">
    {TICKS.map((k) => <span key={k}>{english(k)}</span>)}
  </span>
);
const time = (offset, t) => (t ? `${t}${offset ? " +" + offset : ""}` : "");
/** DD/MM/YYYY boxes, for undated (reusable) sheets. */
const DateComb = () => <Comb n={8} marks={{ 1: "/", 3: "/" }} />;

function Sheet({ d, undated }) {
  const lang = d.language;
  const reference = (r) => ["LAYOVER", "HALT", "CHARGING"].includes(r.activity_type);
  // numbered stops once per route direction (the "stop #" box refers to these numbers)
  const stopLegend = [...new Map(d.runs.filter((r) => r.stops).map((r) => [`${r.route_code} ${r.direction_code}`,
    r.stops.map((st) => `${st.stop_sequence} ${st.location_name}`).join(" · ")])).entries()];
  // identifies the paper: printed at the top of the run table on every page, so each scanned page can be matched
  const ocrId = `DEPOT-TS S${d.schedule_id} V${d.version_number}`;
  const ocrDate = String(d.operating_date).replaceAll("-", "");
  const th = "border border-slate-400 bg-slate-50 px-[0.8mm] py-[0.2mm] text-left align-bottom font-semibold leading-tight";
  const td = "border border-slate-400 px-[0.8mm] py-[0.3mm] align-middle";
  // box rows: no text line - the boxes alone set the height
  const tdBox = "border border-t-0 border-slate-400 px-[0.8mm] py-[0.1mm] align-middle leading-none";
  // free writing: an empty ruled cell, tall enough for a hand-written time or odometer reading
  const tdWrite = "border border-slate-400 px-[0.8mm] align-middle h-[6.4mm]";
  return (
    <section className="sheet relative mx-auto mb-6 bg-white text-[7.5pt] text-ink print:mb-0" style={{ width: SHEET_W, padding: "4.5mm 4mm" }}>
      {/* corner marks for aligning a scanned page */}
      {["left-0 top-0", "right-0 top-0", "left-0 bottom-0", "right-0 bottom-0"].map((c) => (
        <span key={c} className={`absolute ${c} bg-ink`} style={{ width: "4mm", height: "4mm" }} />
      ))}
      <header className="mb-[1.5mm] flex items-end justify-between gap-4 border-b-2 border-ink pb-[1mm]">
        <div>
          <p className="text-[6.5pt] uppercase tracking-wide text-slate-500">{d.company_name} · {d.cost_center}</p>
          <h1 className="text-[12pt] font-bold"><L k="title" lang={lang} /></h1>
        </div>
        <div className="grid grid-cols-[auto_auto_auto_auto] items-end gap-x-3 gap-y-[1mm]">
          {[["bus", <b key="b" className="text-[9.5pt]">{d.fleet_number}</b>], ["registration", <b key="r">{d.registration_number}</b>],
            ["schedule", <b key="s">{d.schedule_code} v{d.version_number}</b>],
            ["date", undated ? <DateComb key="d" /> : <b key="d">{fmtDateLong(d.operating_date)}</b>]].map(([k, v]) => (
            <Fragment key={k}><span className="text-slate-500"><L k={k} lang={lang} small /></span>{v}</Fragment>
          ))}
        </div>
      </header>


      <p className="mb-[1.5mm] text-[6pt] leading-tight text-slate-600">{english("howTo")}{regional("howTo", lang) && <span className="block">{regional("howTo", lang)}</span>}</p>

      <table className="mb-[2mm] w-full border-collapse" style={{ tableLayout: "fixed" }}>
        <thead><tr>
          <th className={th} style={{ width: "22mm" }}><L k="crew" lang={lang} small /></th><th className={th} style={{ width: "10mm" }}><L k="shift" lang={lang} small /></th>
          <th className={th} style={{ width: "38mm" }}><L k="empNo" lang={lang} small /></th><th className={th} style={{ width: "32mm" }}><L k="dutyFrom" lang={lang} small /></th>
          <th className={th} style={{ width: "32mm" }}><L k="dutyTo" lang={lang} small /></th><th className={th}><L k="signature" lang={lang} small /></th></tr></thead>
        <tbody>
          {d.crew.map((c, i) => (
            <tr key={i}>
              <td className={`${td} font-semibold`}><L k={c.role} lang={lang} small /></td><td className={td}>{c.shift || ""}</td>
              <td className={td}><Comb n={8} /></td>
              <td className={td}><Time /><span className="ml-1 text-[6pt] text-slate-500">{time(c.from_day, c.from)}</span></td>
              <td className={td}><Time /><span className="ml-1 text-[6pt] text-slate-500">{time(c.to_day, c.to)}</span></td><td className={td} />
            </tr>
          ))}
          <tr>
            <td className={`${td} font-semibold`}><L k="change" lang={lang} small /></td>
            <td className={td} colSpan={2}><span className="flex items-end gap-2"><span className="text-[6pt] text-slate-500"><L k="newDriver" lang={lang} small /></span><Comb n={8} /></span></td>
            <td className={td}><span className="flex items-end gap-2"><span className="text-[6pt] text-slate-500"><L k="time" lang={lang} small /></span><Time /></span></td>
            <td className={td} colSpan={2}><span className="flex items-end gap-2"><span className="text-[6pt] text-slate-500"><L k="reasonNo" lang={lang} small /></span><Comb n={3} /></span></td>
          </tr>
          {/* another bus ran the schedule from a run onward: its registration, one character per box */}
          <tr>
            <td className={`${td} font-semibold`}><L k="busChange" lang={lang} small /></td>
            <td className={td} colSpan={3}><span className="flex items-end gap-2"><span className="text-[6pt] text-slate-500"><L k="newBusReg" lang={lang} small /></span><Comb n={11} /></span></td>
            <td className={td}><span className="flex items-end gap-2"><span className="text-[6pt] text-slate-500"><L k="fromRun" lang={lang} small /></span><Comb n={2} /></span></td>
            <td className={td}><span className="flex items-end gap-2"><span className="text-[6pt] text-slate-500"><L k="reasonNo" lang={lang} small /></span><Comb n={3} /></span></td>
          </tr>
        </tbody>
      </table>

      {/* One row per run, laid out like the depot's own form: everything about the departure on the left,
          everything about the arrival on the right. Only Ran / Cut / Not are boxes; the rest is written
          freely into the ruled cells. Layovers, charging and halts are reference lines, not rows to fill. */}
      <table className="w-full border-collapse" style={{ tableLayout: "fixed" }}>
        <colgroup>
          {["5mm", "29mm", "29mm", "15mm", "16mm", "12mm", "18mm", "16mm", "12mm", "18mm", "11mm", null]
            .map((w, i) => <col key={i} style={w ? { width: w } : undefined} />)}
        </colgroup>
        <thead>
          {/* repeats on every page of a long day, so each scanned page carries the sheet's identity */}
          <tr><th colSpan={12} className="pb-[0.3mm] font-normal leading-none">
            <span className="flex items-end justify-between gap-3">
              <span className="text-left text-[5.5pt] font-semibold leading-tight text-ink">
                {undated && <>v{d.version_number} · from {fmtDateLong(d.version_valid_from)}{d.version_valid_to ? ` to ${fmtDateLong(d.version_valid_to)}` : ""} — {english("discardOld")}
                  {regional("discardOld", lang) && <span className="block font-normal">{regional("discardOld", lang)}</span>}</>}
              </span>
              <span className="inline-flex shrink-0 items-end gap-2 font-mono text-[7.5pt] tracking-[0.1em] text-ink">{ocrId} {undated ? <DateComb /> : ocrDate} · {d.fleet_number}</span>
            </span>
          </th></tr>
          <tr>
            <th className={th}>#</th>
            <th className={th}><L k="from" lang={lang} small /></th>
            <th className={th}><L k="to" lang={lang} small /></th>
            <th className={th}><TickHead /></th>
            <th className={`${th} bg-slate-100`}><span className="flex items-end justify-between"><L k="departed" lang={lang} small /></span></th>
            <th className={`${th} bg-slate-100`}><L k="startSoc" lang={lang} small /></th>
            <th className={`${th} bg-slate-100`}><L k="odoStart" lang={lang} small /></th>
            <th className={th}><span className="flex items-end justify-between"><L k="arrived" lang={lang} small /><span className="text-[5.5pt] font-normal text-slate-500">+0/1</span></span></th>
            <th className={th}><L k="endSoc" lang={lang} small /></th>
            <th className={th}><L k="odoEnd" lang={lang} small /></th>
            <th className={th}><L k="reasonNo" lang={lang} small /></th>
            <th className={th}><L k="endStop" lang={lang} small /></th>
          </tr>
        </thead>
        <tbody>
          {d.runs.map((r, i) => {
            const what = r.trip_number ? `${r.trip_number} ${r.route_code} ${r.direction_code}`
              : `${english(r.activity_type)}${regional(r.activity_type, lang) ? ` / ${regional(r.activity_type, lang)}` : ""}`;
            const when = `${time(r.start_day_offset, r.start_time)}–${time(r.end_day_offset, r.end_time)}${r.planned_km ? ` · ${r.planned_km} km` : ""}`;
            // the line under the departure point has one column's width: trip number (or what the run is),
            // the planned window, and the km only where there are any
            const runLine = `${r.trip_number || englishOnly(english(r.activity_type))} · ${time(r.start_day_offset, r.start_time)}–${time(r.end_day_offset, r.end_time)}${r.trip_number && r.planned_km ? ` · ${r.planned_km} km` : ""}`;
            if (reference(r)) {
              // layover, charging and halt: shown so the driver sees the gap, nothing to fill in
              const where = `${place(r.origin_name, r.origin_name_local)}${r.origin_code !== r.destination_code ? ` → ${place(r.destination_name, r.destination_name_local)}` : ""}`;
              return (
                <tr key={r.activity_id} className="bg-slate-50 text-[5.5pt] leading-none text-slate-500" style={{ breakInside: "avoid" }}>
                  <td className="border border-slate-300 px-[0.8mm] py-[0.5mm]">{i + 1}</td>
                  <td className="truncate border border-slate-300 px-[0.8mm] py-[0.5mm]" colSpan={11}>
                    <b>{what}</b> · {when} · {where}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={r.activity_id} style={{ breakInside: "avoid" }}>
                <td className={`${td} text-center align-middle text-[7pt] font-semibold tabular-nums`}>{i + 1}</td>
                {/* the route is printed as on the depot's form - English, the regional name under it - and the
                    run's own line (trip number, planned window, km) sits under the departure point */}
                <td className={`${td} leading-[1.0]`}>
                  <span className="block truncate text-[6.2pt] font-semibold">{r.origin_name}</span>
                  {r.origin_name_local && <span className="block truncate text-[5.2pt] text-slate-600">{r.origin_name_local}</span>}
                  <span className="block truncate text-[5pt] text-slate-500">{runLine}</span>
                </td>
                <td className={`${td} leading-[1.0]`}>
                  <span className="block truncate text-[6.2pt] font-semibold">{r.destination_name}</span>
                  {r.destination_name_local && <span className="block truncate text-[5.2pt] text-slate-600">{r.destination_name_local}</span>}
                </td>
                <td className={tdWrite}><span className="grid grid-cols-3 justify-items-center"><TickBox /><TickBox hidden={!r.trip_number} /><TickBox /></span></td>
                <td className={`${tdWrite} bg-slate-50/60`} /><td className={`${tdWrite} bg-slate-50/60`} /><td className={`${tdWrite} bg-slate-50/60`} />
                <td className={tdWrite} /><td className={tdWrite} /><td className={tdWrite} />
                <td className={tdWrite} /><td className={tdWrite}>{r.trip_number ? null : <span className="block text-center text-[6pt] text-slate-300">—</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* the depot's own closing block: what the driver noticed, the day's km, and who signed for it */}
      <div className="mt-[1.5mm] grid grid-cols-[1fr_52mm] gap-x-3 text-[6pt]" style={{ breakInside: "avoid" }}>
        <div className="border border-slate-400 px-[1mm] py-[0.6mm]">
          <span className="font-semibold"><L k="observations" lang={lang} small /></span>
          <span className="mt-[0.5mm] block h-[10mm]" />
        </div>
        <div className="border border-slate-400 px-[1mm] py-[0.6mm]">
          {[["finalRunKm", null], ["deadKm", null]].map(([k]) => (
            <p key={k} className="flex items-end gap-1 border-b border-dotted border-slate-300 pb-[0.6mm] pt-[0.4mm]">
              <span className="text-slate-600">{english(k)}{regional(k, lang) ? ` / ${regional(k, lang)}` : ""}</span>
            </p>
          ))}
          <p className="flex items-center gap-2 pt-[0.8mm]">
            <span className="text-slate-600">{english("dutyCompleted")}</span>
            {["yes", "no"].map((k) => (
              <span key={k} className="inline-flex items-center gap-[0.6mm]"><TickBox />{english(k)}</span>
            ))}
          </p>
        </div>
      </div>

      <footer className="mt-[1.5mm] grid grid-cols-[2.1fr_1fr_0.6fr] gap-x-3 text-[6pt] leading-snug [&>*]:min-w-0" style={{ breakInside: "avoid" }}>
        <div>
          <p className="font-semibold"><L k="reasonCodes" lang={lang} small /></p>
          <p className="columns-3 gap-2 text-[5.6pt] leading-[1.15]">{[...d.reasons].sort((a, b) => a.id - b.id).map((x) => {
            const loc = reasonLocal(x, lang);
            return <span key={x.id} className="block"><b className="font-mono">{String(x.id).padStart(3, "0")}</b> {x.name}{loc && <span className="text-slate-600"> ({loc})</span>}</span>;
          })}</p>
        </div>
        <div>
          {stopLegend.length > 0 && <>
            <p className="font-semibold"><L k="endStop" lang={lang} small /></p>
            {stopLegend.map(([dir, stops]) => <span key={dir} className="block"><b>{dir}</b>: {stops}</span>)}
          </>}
        </div>
        {/* the four signatures the depot's own sheet carries, each with room above the rule to sign in */}
        <div className="col-span-3 mt-[1mm] grid grid-cols-4 gap-x-5">
          {["DRIVER", "CONDUCTOR", "stationIncharge", "operatorIncharge"].map((k) => (
            <div key={k} className="text-center">
              <span className="block h-[12mm]" />
              <span className="block border-t border-slate-500 pt-[0.5mm]"><L k={k} lang={lang} small /></span>
            </div>
          ))}
        </div>
      </footer>
    </section>
  );
}

/** Pre-filled OCR-ready trip sheets: one schedule (?schedule=) or every bus on the date. A4 portrait, true size. */
export default function PrintTripSheet() {
  const [sp] = useSearchParams();
  const date = sp.get("date");
  const schedule = sp.get("schedule");
  const undated = sp.get("undated") === "1";
  const { data, error } = useApi(`/trip-sheets/print-data?date=${date}${schedule ? `&schedule_id=${schedule}` : ""}`);
  if (error) return <p className="p-6 text-danger">{error}</p>;
  if (!data) return <Spinner />;
  return (
    <div className="bg-slate-100 py-4 print:bg-white print:py-0">
      <style>{"@page { size: A4 portrait; margin: 5mm; } @media print { .sheet + .sheet { break-before: page; } }"}</style>
      <div className="mx-auto mb-3 flex items-center justify-between print:hidden" style={{ width: SHEET_W }}>
        <p className="text-sm text-slate-600">{data.length} sheet{data.length === 1 ? "" : "s"} · {undated ? `undated (reusable) - plan in force on ${fmtDateLong(date)}` : fmtDateLong(date)} · A4 portrait · print at 100% (not "fit to page"){undated ? " · set the number of copies in the print dialog" : ""}</p>
        <Button icon={Printer} onClick={() => window.print()}>Print</Button>
      </div>
      {data.length === 0 ? <p className="text-center text-sm text-slate-500">No published schedule operates on this date.</p> : data.map((d) => <Sheet key={d.schedule_id} d={d} undated={undated} />)}
    </div>
  );
}
