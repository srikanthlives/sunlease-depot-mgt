import { soc } from "../lib/format";
import { socOf, socTotals } from "../lib/soc";

export { socOf };

/** One activity's planned SOC: start → end, with the change as a coloured triangle.
 *  A rise is green (charging), a drop red (running); an unchanged SOC gets no triangle.
 *  The change is in SOC points, which is what the planned readings are recorded in. */
export default function SocCell({ of }) {
  const s = soc(of);
  if (!s) return <span className="text-slate-300">—</span>;
  if (s.end === null) {
    return <span className="whitespace-nowrap tabular-nums">{s.start}% <span className="text-slate-400">→ ?</span></span>;
  }
  const up = s.delta > 0;
  return (
    <span className="whitespace-nowrap tabular-nums">
      {s.start}% <span className="text-slate-400">→</span> {s.end}%
      {s.delta !== 0 && (
        <span className={`ml-1.5 font-medium ${up ? "text-ok" : "text-danger"}`}
          title={`${Math.abs(s.delta)} SOC points ${up ? "gained" : "used"}`}>
          <span aria-hidden="true">{up ? "▲" : "▼"}</span>
          <span className="sr-only">{up ? "up" : "down"} </span>{Math.abs(s.delta)}%
        </span>
      )}
    </span>
  );
}

/** Footer counterpart of SocCell: what the whole cycle consumes and puts back. */
export function SocTotals({ activities }) {
  const t = socTotals(activities);
  if (!t.used && !t.gained) return <span className="text-slate-300">—</span>;
  return (
    <span className="whitespace-nowrap tabular-nums" title="SOC points used by running, gained by charging">
      <span className="text-danger"><span aria-hidden="true">▼</span> used {t.used}%</span>
      {t.gained > 0 && <span className="text-ok"> · <span aria-hidden="true">▲</span> gained {t.gained}%</span>}
      <span className="text-slate-500"> · net {t.net > 0 ? "+" : ""}{t.net}%</span>
    </span>
  );
}
