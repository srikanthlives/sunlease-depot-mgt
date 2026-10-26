import { createContext, useCallback, useContext, useState } from "react";
import { CheckCircle2, AlertTriangle, X } from "lucide-react";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, kind = "ok") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 3000);
  }, []);
  const api = { ok: (m) => push(m, "ok"), error: (m) => push(m, "error") };
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 print:hidden" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role="status"
            className={`flex max-w-md items-start gap-2 rounded-lg border bg-white px-4 py-3 text-sm shadow-lg ${t.kind === "error" ? "border-danger/40" : "border-ok/40"}`}>
            {t.kind === "error" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" />}
            <span className="text-ink">{t.message}</span>
            <button tabIndex={-1} className="ml-auto text-slate-400 hover:text-slate-600" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
