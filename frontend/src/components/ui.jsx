import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, Loader2, Keyboard } from "lucide-react";
import clsx from "clsx";
import { focusFirst, useFormKeys } from "../lib/keys";
import { label } from "../lib/format";

export function Button({ variant = "primary", size = "md", icon: Icon, loading, className, children, ...props }) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 focus-visible:ring-brand-300",
    secondary: "border border-slate-300 bg-white text-ink hover:bg-slate-50 focus-visible:ring-brand-200",
    ghost: "text-slate-600 hover:bg-slate-100 focus-visible:ring-brand-200",
    danger: "bg-danger text-white hover:brightness-95 focus-visible:ring-danger/30",
    success: "bg-ok text-white hover:brightness-95 focus-visible:ring-ok/30",
  }[variant];
  const sz = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-1.5 text-sm", lg: "px-4 py-2 text-sm" }[size];
  return (
    <button className={clsx("inline-flex items-center justify-center gap-1.5 rounded-md font-medium outline-none transition focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50", styles, sz, className)}
      disabled={loading || props.disabled} {...props}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : Icon ? <Icon className="h-4 w-4" /> : null}
      {children}
    </button>
  );
}

export function IconButton({ icon: Icon, title, className, ...props }) {
  return (
    <button type="button" tabIndex={-1} title={title} aria-label={title}
      className={clsx("rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-ink disabled:opacity-30", className)} {...props}>
      <Icon className="h-4 w-4" />
    </button>
  );
}

export function Card({ title, actions, className, children, padded = true }) {
  return (
    <section className={clsx("rounded-xl border border-slate-200 bg-white shadow-card", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
          {typeof title === "string" ? <h2 className="text-sm font-semibold text-ink">{title}</h2> : title}
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 print:hidden">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {/* bottom-aligned: a labelled input is taller than a button, so centring would offset the buttons */}
      <div className="flex flex-wrap items-end gap-2">{actions}</div>
    </div>
  );
}

const BADGE = {
  ACTIVE: "bg-ok/10 text-[#0a6e0a] ring-ok/30", PUBLISHED: "bg-ok/10 text-[#0a6e0a] ring-ok/30",
  DRAFT: "bg-warn/15 text-[#8a5a00] ring-warn/40", TO_BE_CONFIRMED: "bg-warn/15 text-[#8a5a00] ring-warn/40",
  INACTIVE: "bg-slate-100 text-slate-600 ring-slate-300", RETIRED: "bg-slate-100 text-slate-600 ring-slate-300",
  SUPERSEDED: "bg-slate-100 text-slate-600 ring-slate-300", NON_PAYABLE: "bg-slate-100 text-slate-700 ring-slate-300",
  PAYABLE: "bg-brand-50 text-brand-700 ring-brand-200",
  ERROR: "bg-danger/10 text-danger ring-danger/30", WARNING: "bg-warn/15 text-[#8a5a00] ring-warn/40",
  LIVE: "bg-ok/10 text-[#0a6e0a] ring-ok/30", APPROVED: "bg-ok/10 text-[#0a6e0a] ring-ok/30", OPERATED: "bg-ok/10 text-[#0a6e0a] ring-ok/30",
  SCHEDULED: "bg-brand-50 text-brand-700 ring-brand-200", SUBMITTED: "bg-brand-50 text-brand-700 ring-brand-200",
  ENDED: "bg-slate-100 text-slate-600 ring-slate-300", NOT_STARTED: "bg-slate-100 text-slate-600 ring-slate-300",
  PENDING: "bg-slate-100 text-slate-600 ring-slate-300",
  PARTIAL: "bg-warn/15 text-[#8a5a00] ring-warn/40", CANCELLED: "bg-danger/10 text-danger ring-danger/30",
};

export function Badge({ value, children, className }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset",
      BADGE[value] || "bg-slate-100 text-slate-700 ring-slate-200", className)}>
      {children ?? label(value)}
    </span>
  );
}

/** Modal with focus on first field, Enter-to-next, Ctrl+S save, Esc cancel. */
export function Modal({ open, title, onClose, onSave, children, footer, wide, xwide }) {
  const ref = useRef(null);
  const keys = useFormKeys({ onSave, onCancel: onClose });
  useEffect(() => {
    if (open) setTimeout(() => focusFirst(ref.current), 30);
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 pt-[6vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}
        className={clsx("w-full rounded-xl bg-white shadow-2xl", xwide ? "max-w-6xl" : wide ? "max-w-3xl" : "max-w-lg")}
        onKeyDown={keys}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <IconButton icon={X} title="Close (Esc)" onClick={onClose} />
        </header>
        <div className="max-h-[75vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer !== null && (
          <footer className="flex items-center justify-between gap-2 border-t border-slate-100 px-5 py-3">
            <span className="hidden text-xs text-slate-400 sm:inline">Enter next field · Ctrl+S save · Esc cancel</span>
            <div className="flex gap-2">
              {footer || (
                <>
                  <Button variant="secondary" onClick={onClose} type="button">Cancel</Button>
                  <Button onClick={onSave} type="button">Save</Button>
                </>
              )}
            </div>
          </footer>
        )}
      </div>
    </div>,
    document.body
  );
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-sm text-slate-500">
      {Icon && <Icon className="h-8 w-8 text-slate-300" />}
      <p className="font-medium text-slate-600">{title}</p>
      {children}
    </div>
  );
}

export function Spinner() {
  return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div>;
}

/** `rowClassName(row)` tints a row, e.g. a record that failed validation. */
export function Table({ columns, rows, onRowClick, empty = "No records", rowKey, rowClassName }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
            {columns.map((c) => <th key={c.key} className={clsx("px-3 py-2 font-medium", c.className)}>{c.title}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={columns.length} className="px-3 py-8 text-center text-slate-400">{empty}</td></tr>}
          {rows.map((r, i) => (
            <tr key={rowKey ? rowKey(r) : i} onClick={onRowClick ? () => onRowClick(r) : undefined}
              tabIndex={onRowClick ? 0 : undefined} onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(r) : undefined}
              className={clsx("border-b border-slate-100 last:border-0", onRowClick && "cursor-pointer outline-none hover:bg-brand-50/50 focus:bg-brand-50", rowClassName && rowClassName(r))}>
              {columns.map((c) => <td key={c.key} className={clsx("px-3 py-2", c.className)}>{c.render ? c.render(r) : r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const SHORTCUTS = [
  ["Enter", "Next field (saves on the last field)"], ["Shift + Enter", "Previous field"], ["Tab / Shift + Tab", "Next / previous field"],
  ["Ctrl + S", "Save the open form"], ["Esc", "Cancel / close"], ["↑ ↓ then Enter", "Pick from a search list"],
  ["Dates", "21-Oct-2026 · 211026 · 21-oct · 21 · T (today) · +1 / -1"], ["Times", "930 → 09:30 · 2230 → 22:30"],
  ["+ / -  in a time", "Change the day offset (+1 = next day)"], ["?", "Show this help"],
];

export function ShortcutHelp() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const h = (e) => {
      const tag = e.target.tagName;
      if (e.key === "?" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) setOpen((o) => !o);
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  return (
    <>
      <button tabIndex={-1} onClick={() => setOpen(true)} title="Keyboard shortcuts (?)" className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-brand-100 hover:bg-white/10">
        <Keyboard className="h-4 w-4" /> <span className="hidden md:inline">Shortcuts</span>
      </button>
      <Modal open={open} title="Keyboard shortcuts" onClose={() => setOpen(false)} footer={null}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          {SHORTCUTS.map(([k, v]) => (
            <div key={k} className="contents">
              <dt><kbd className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 font-mono text-xs">{k}</kbd></dt>
              <dd className="text-slate-600">{v}</dd>
            </div>
          ))}
        </dl>
      </Modal>
    </>
  );
}
