import { useState } from "react";

/** Simple hover tooltip layer for SVG charts. Wrap the chart; call show(e, content)/hide(). */
export function useTooltip() {
  const [tip, setTip] = useState(null);
  const show = (e, content) => {
    const host = e.currentTarget.closest("[data-tip-host]");
    const r = host.getBoundingClientRect();
    setTip({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, content });
  };
  const hide = () => setTip(null);
  const node = tip ? (
    <div className="pointer-events-none absolute z-20 max-w-xs rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-ink shadow-lg print:hidden"
      style={{ left: Math.min(tip.x + 12, tip.w - 230), top: tip.y + 14 }}>
      {tip.content}
    </div>
  ) : null;
  return { show, hide, node };
}
