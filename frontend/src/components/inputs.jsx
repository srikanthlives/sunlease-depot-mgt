import { useEffect, useId, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronDown } from "lucide-react";
import clsx from "clsx";
import { fmtDate, parseDate, parseTime } from "../lib/format";

const base =
  "w-full rounded-md border bg-white px-2.5 py-1.5 text-sm text-ink outline-none transition placeholder:text-slate-400 " +
  "focus:border-brand-500 focus:ring-2 focus:ring-brand-200 disabled:bg-slate-50 disabled:text-slate-500";
const border = (err) => (err ? "border-danger focus:border-danger focus:ring-danger/20" : "border-slate-300");

export function Field({ label, hint, error, required, className, children, htmlFor }) {
  return (
    <div className={clsx("flex flex-col gap-1", className)}>
      {label && (
        <label htmlFor={htmlFor} className="text-xs font-medium text-slate-600">
          {label}
          {required && <span className="text-danger"> *</span>}
        </label>
      )}
      {children}
      {error ? <span className="text-xs text-danger">{error}</span> : hint ? <span className="text-xs text-slate-500">{hint}</span> : null}
    </div>
  );
}

export function TextInput({ label, error, hint, required, className, inputClassName, ...props }) {
  const id = useId();
  return (
    <Field label={label} error={error} hint={hint} required={required} className={className} htmlFor={id}>
      <input id={id} aria-invalid={!!error} className={clsx(base, border(error), inputClassName)} onFocus={(e) => e.target.select()} {...props} />
    </Field>
  );
}

export function TextArea({ label, error, className, ...props }) {
  const id = useId();
  return (
    <Field label={label} error={error} className={className} htmlFor={id} hint="Ctrl+Enter to move on">
      <textarea id={id} rows={2} className={clsx(base, border(error))} {...props} />
    </Field>
  );
}

export function Select({ label, hint, error, required, options, value, onChange, className, placeholder, ...props }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} required={required} className={className} htmlFor={id}>
      <select id={id} aria-invalid={!!error} className={clsx(base, border(error), "pr-7")} value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        onKeyDown={(e) => {
          // ↑/↓ step through options on every platform (macOS would open the popup instead)
          if ((e.key !== "ArrowDown" && e.key !== "ArrowUp") || e.altKey) return;
          e.preventDefault();
          const vals = options.map((o) => String(o.value));
          const i = vals.indexOf(String(value ?? ""));
          const j = e.key === "ArrowDown" ? Math.min(i + 1, vals.length - 1) : Math.max(i - 1, 0);
          if (vals[j] !== undefined && j !== i) onChange(options[j].value);
        }} {...props}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </Field>
  );
}

export function Checkbox({ label, checked, onChange, className }) {
  return (
    <label className={clsx("flex items-center gap-2 text-sm text-ink", className)}>
      <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-300"
        checked={!!checked} onChange={(e) => onChange(e.target.checked)}
        onKeyDown={(e) => { if (e.key === "Enter") { /* handled by form: move next */ } }} />
      {label}
    </label>
  );
}

/** Text input that parses on blur/Enter. `parse(text)` -> {value} | {error}; `format(value)` -> text.
 *  `suggest`: value used when Enter is pressed on an empty field (e.g. previous stop's departure). */
function useParsedInput({ value, onChange, parse, format, suggest }) {
  const [text, setTextState] = useState(format(value));
  const [error, setError] = useState(null);
  const textRef = useRef(text);
  const focused = useRef(false);
  const setText = (t) => { textRef.current = t; setTextState(t); };
  useEffect(() => {
    if (!focused.current) setText(format(value));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  function commit(raw = textRef.current) {
    const r = parse(raw);
    if (r.error) {
      setError(r.error);
      return false;
    }
    setError(null);
    setText(format(r.value));
    if (r.value !== value) onChange(r.value);
    return true;
  }
  const handlers = {
    value: text,
    onChange: (e) => { setText(e.target.value); if (error) setError(null); },
    onFocus: (e) => { focused.current = true; e.target.select(); },
    onBlur: () => { focused.current = false; commit(); },
    onKeyDown: (e) => {
      if (e.key !== "Enter") return;
      if (!textRef.current.trim() && suggest) commit(format(suggest));
      else if (!commit()) e.preventDefault(); // stay on an invalid field
    },
  };
  return { handlers, error, setText, commit };
}

/** DD-MMM-YYYY date field. value/onChange use ISO. */
export function DateInput({ label, value, onChange, error: extErr, required, className, base: baseDate, autoFocus, disabled, compact }) {
  const id = useId();
  const picker = useRef(null);
  const { handlers, error } = useParsedInput({
    value, onChange,
    parse: (t) => { const r = parseDate(t, { base: baseDate || value }); return r.error ? r : { value: r.iso }; },
    format: (v) => fmtDate(v),
  });
  const err = error || extErr;
  const input = (
    <div className="relative">
      <input id={id} autoFocus={autoFocus} disabled={disabled} aria-invalid={!!err} placeholder="DD-MMM-YYYY" autoComplete="off"
        className={clsx(base, border(err), "pr-8 tabular-nums", compact ? "w-32" : "")} {...handlers}
        title="Type 21-Oct-2026, 211026, 21-oct, 21, T (today) or +1 / -1" />
      <button type="button" tabIndex={-1} disabled={disabled} onClick={() => picker.current?.showPicker?.()}
        className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-brand-600" aria-label="Open calendar">
        <CalendarDays className="h-4 w-4" />
      </button>
      <input ref={picker} type="date" tabIndex={-1} aria-hidden className="pointer-events-none absolute bottom-0 left-0 h-0 w-0 opacity-0"
        value={value || ""} onChange={(e) => onChange(e.target.value || null)} />
    </div>
  );
  if (!label && !err) return <div className={className}>{input}</div>;
  return <Field label={label} error={err} required={required} className={className} htmlFor={id}>{input}</Field>;
}

/** 24-hour HH:MM field. `930` -> 09:30. Optional day offset beside it: '+' / '-' keys bump the offset. */
export function TimeInput({ label, value, onChange, offset, onOffsetChange, error: extErr, required, className, autoFocus, disabled, placeholder = "HH:MM", suggest }) {
  const id = useId();
  const { handlers, error } = useParsedInput({
    value, onChange, suggest,
    parse: (t) => { const r = parseTime(t); return r.error ? r : { value: r.time }; },
    format: (v) => v || "",
  });
  const err = error || extErr;
  const withOffset = onOffsetChange !== undefined;
  const keyDown = (e) => {
    handlers.onKeyDown(e);
    if (!withOffset) return;
    if (e.key === "+" || e.key === "*") { e.preventDefault(); onOffsetChange((Number(offset) || 0) + 1); }
    if (e.key === "-" && (Number(offset) || 0) > 0) { e.preventDefault(); onOffsetChange(Number(offset) - 1); }
  };
  const control = (
    <div className="flex items-stretch">
      <input id={id} autoFocus={autoFocus} disabled={disabled} aria-invalid={!!err} placeholder={placeholder} autoComplete="off" inputMode="numeric"
        className={clsx(base, border(err), "w-[4.6rem] tabular-nums", withOffset && "rounded-r-none")} {...handlers} onKeyDown={keyDown}
        title={withOffset ? "24-hour time. Press + or - to change the day offset" : "24-hour time, e.g. 930 = 09:30"} />
      {withOffset && <OffsetInput value={offset} onChange={onOffsetChange} disabled={disabled} />}
    </div>
  );
  if (!label && !err) return <div className={className}>{control}</div>;
  return <Field label={label} error={err} required={required} className={className} htmlFor={id}>{control}</Field>;
}

/** Day offset: +0, +1, +2 ... Tab-stop so it can be typed directly. */
export function OffsetInput({ value, onChange, disabled }) {
  const v = Number(value) || 0;
  return (
    <input disabled={disabled} inputMode="numeric" aria-label="Day offset"
      className={clsx("w-11 rounded-r-md border border-l-0 px-1 text-center text-xs font-semibold tabular-nums outline-none focus:ring-2 focus:ring-brand-200",
        v > 0 ? "border-slate-300 bg-brand-50 text-brand-700" : "border-slate-300 bg-slate-50 text-slate-500")}
      value={`+${v}`} onFocus={(e) => e.target.select()}
      onKeyDown={(e) => {
        if (e.key === "+" || e.key === "ArrowUp" || e.key === "*") { e.preventDefault(); onChange(v + 1); }
        if ((e.key === "-" || e.key === "ArrowDown") && v > 0) { e.preventDefault(); onChange(v - 1); }
      }}
      onChange={(e) => { const n = parseInt(e.target.value.replace(/\D/g, ""), 10); onChange(Number.isNaN(n) ? 0 : Math.min(n, 9)); }}
      title="Day offset from the operating date. + / - or arrow keys" />
  );
}

/** Number field without spinners; selects on focus; range-checked on blur. */
export function NumberInput({ label, value, onChange, min, max, step, error: extErr, required, className, placeholder, suffix, autoFocus, disabled, integer }) {
  const id = useId();
  const { handlers, error } = useParsedInput({
    value, onChange,
    parse: (t) => {
      const s = String(t).trim().replace(/,/g, "");
      if (s === "") return { value: null };
      if (!/^-?\d*\.?\d*$/.test(s) || s === "." || s === "-") return { error: "Enter a number" };
      const n = Number(s);
      if (integer && !Number.isInteger(n)) return { error: "Whole numbers only" };
      if (min !== undefined && n < min) return { error: `Minimum ${min}` };
      if (max !== undefined && n > max) return { error: `Maximum ${max}` };
      return { value: n };
    },
    format: (v) => (v === null || v === undefined || v === "" ? "" : String(Number(v))),
  });
  const err = error || extErr;
  const control = (
    <div className="relative">
      <input id={id} inputMode="decimal" autoFocus={autoFocus} disabled={disabled} aria-invalid={!!err} placeholder={placeholder} autoComplete="off" step={step}
        className={clsx(base, border(err), "tabular-nums text-right", suffix && "pr-9")} {...handlers} />
      {suffix && <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400">{suffix}</span>}
    </div>
  );
  if (!label && !err) return <div className={className}>{control}</div>;
  return <Field label={label} error={err} required={required} className={className} htmlFor={id}>{control}</Field>;
}

/**
 * Type-ahead picker. options: [{value, label, sub}] . Arrow keys move, Enter/Tab picks, Esc closes.
 * Matches on label and sub (code + name), prefix matches first.
 */
export function Combobox({ label, value, onChange, options, error, required, className, placeholder = "Type to search", autoFocus, disabled }) {
  const id = useId();
  const selected = options.find((o) => String(o.value) === String(value));
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const listRef = useRef(null);
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options.slice(0, 50);
    const score = (o) => {
      const l = `${o.label} ${o.sub || ""}`.toLowerCase();
      if (l.startsWith(q)) return 0;
      if (l.split(/[\s\-–]+/).some((w) => w.startsWith(q))) return 1;
      return l.includes(q) ? 2 : 9;
    };
    return options.map((o) => [score(o), o]).filter(([s]) => s < 9).sort((a, b) => a[0] - b[0]).map(([, o]) => o).slice(0, 50);
  }, [query, options]);
  useEffect(() => setHi(0), [query]);
  useEffect(() => {
    listRef.current?.children[hi]?.scrollIntoView({ block: "nearest" });
  }, [hi]);

  const pick = (o) => {
    onChange(o ? o.value : null);
    setQuery("");
    setOpen(false);
  };
  const keyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setHi((h) => Math.min(h + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); setQuery(""); }
    else if (open && matches[hi] && (e.key === "Enter" || (e.key === "Tab" && query))) {
      pick(matches[hi]); // Enter then bubbles to the form handler, which moves to the next field
    }
  };
  const display = open || query ? query : selected ? selected.label : "";
  const control = (
    <div className="relative">
      <input id={id} autoFocus={autoFocus} disabled={disabled} aria-invalid={!!error} role="combobox" aria-expanded={open} autoComplete="off"
        placeholder={selected ? selected.label : placeholder}
        className={clsx(base, border(error), "truncate", selected?.sub && !open && !query ? "pr-20" : "pr-7")} value={display}
        onFocus={(e) => e.target.select()}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onBlur={() => setTimeout(() => { setOpen(false); setQuery(""); }, 120)}
        onKeyDown={keyDown} />
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      {selected?.sub && !open && !query && (
        <span className="pointer-events-none absolute right-7 top-1/2 -translate-y-1/2 truncate text-xs text-slate-400">{selected.sub}</span>
      )}
      {open && (
        <ul ref={listRef} className="absolute z-50 mt-1 max-h-60 w-full min-w-[14rem] overflow-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg">
          {matches.length === 0 && <li className="px-3 py-2 text-slate-400">No matches</li>}
          {matches.map((o, i) => (
            <li key={o.value} onMouseDown={(e) => { e.preventDefault(); pick(o); }} onMouseEnter={() => setHi(i)}
              className={clsx("flex cursor-pointer items-center justify-between gap-3 px-3 py-1.5", i === hi ? "bg-brand-50 text-brand-800" : "text-ink")}>
              <span className="truncate">{o.label}</span>
              {o.sub && <span className="shrink-0 text-xs text-slate-400">{o.sub}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
  if (!label && !error) return <div className={className}>{control}</div>;
  return <Field label={label} error={error} required={required} className={className} htmlFor={id}>{control}</Field>;
}
