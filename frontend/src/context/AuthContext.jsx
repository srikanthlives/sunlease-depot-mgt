import { createContext, useCallback, useContext, useEffect, useState } from "react";
import client, { CC_KEY } from "../api/client";

const AuthContext = createContext(null);
const RANK = { VIEWER: 1, MIS: 2, SCHEDULER: 3, PUBLISHER: 4, ADMIN: 5 };
export const ALL = "all";

function stored(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}

/** Keep the chosen cost center if the user still has it; otherwise fall back to their first one. */
function pickCc(wanted, ccs) {
  if (wanted === ALL && ccs.length > 1) return ALL;
  if (ccs.some((m) => String(m.cost_center_id) === String(wanted))) return String(wanted);
  return ccs.length ? String(ccs[0].cost_center_id) : null;
}

export function AuthProvider({ children }) {
  // session = { user, is_super_admin, cost_centers: [{cost_center_id, cost_center_code, company_id, company_name, role, ...}] }
  const [session, setSession] = useState(() => stored("depot_session", null));
  const [cc, setCcState] = useState(() => localStorage.getItem(CC_KEY));

  const apply = useCallback((s) => {
    localStorage.setItem("depot_session", JSON.stringify(s));
    setSession(s);
    const next = pickCc(localStorage.getItem(CC_KEY), s.cost_centers);
    if (next) localStorage.setItem(CC_KEY, next); else localStorage.removeItem(CC_KEY);
    setCcState(next);
  }, []);

  /** Re-read the user's cost centers (they change when a super admin edits organisation or roles). */
  const refresh = useCallback(() => client.get("/auth/me").then(({ data }) => apply(data)).catch(() => {}), [apply]);
  useEffect(() => {
    if (session) refresh();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function login(username, password) {
    const { data } = await client.post("/auth/login", { username, password });
    localStorage.setItem("depot_token", data.access_token);
    apply({ user: data.user, is_super_admin: data.is_super_admin, cost_centers: data.cost_centers });
  }

  function logout() {
    localStorage.removeItem("depot_token");
    localStorage.removeItem("depot_session");
    setSession(null);
  }

  const setCc = (value) => {
    localStorage.setItem(CC_KEY, String(value));
    setCcState(String(value));
  };

  const ccs = session?.cost_centers || [];
  const isSuper = !!session?.is_super_admin;
  const member = (id) => ccs.find((m) => String(m.cost_center_id) === String(id));
  const rankIn = (id) => (isSuper ? 99 : RANK[member(id)?.role] || 0);
  /** Role check on a record that belongs to cost center `id` (works in the All view too). */
  const canIn = (id, role) => rankIn(id) >= RANK[role];
  /** Company-level records (locations): the best role in any cost center of that company. */
  const canInCompany = (companyId, role) => isSuper || ccs.some((m) => m.company_id === companyId && RANK[m.role] >= RANK[role]);
  /** Role in the selected cost center. The All view is read-only, so only VIEWER passes there. */
  const can = (role) => (cc === ALL ? role === "VIEWER" && ccs.length > 0 : !!cc && canIn(cc, role));
  const isAll = cc === ALL;
  const current = isAll ? null : member(cc);
  const ccCode = (id) => member(id)?.cost_center_code || "—";
  const companyOf = (id) => member(id)?.company_id ?? null;
  const adminAnywhere = isSuper || ccs.some((m) => m.role === "ADMIN");

  return (
    <AuthContext.Provider value={{
      user: session?.user, isSuper, costCenters: ccs, cc, setCc, isAll, current, login, logout, refresh,
      can, canIn, canInCompany, ccCode, companyOf, adminAnywhere,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
