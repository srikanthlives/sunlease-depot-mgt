import axios from "axios";

// Dev: Vite on 5173, API on 8000. Production: same origin (FastAPI serves the build).
export const BASE_URL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

const client = axios.create({ baseURL: `${BASE_URL}/api` });
// the cost center being worked in ("all" = the read-only All my cost centers view)
export const CC_KEY = "depot_cc";

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("depot_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const cc = localStorage.getItem(CC_KEY);
  if (cc) config.headers["X-Cost-Center-Id"] = cc;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && !err.config.url.includes("/auth/login")) {
      localStorage.removeItem("depot_token");
      localStorage.removeItem("depot_session");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export default client;

/** Turn any API error into one readable line. */
export function apiErrorMessage(err) {
  const detail = err?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== "body").join(".") : "";
        const msg = (d.msg || "").replace(/^Value error,\s*/, "");
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  if (typeof detail === "string") return detail;
  return err?.message || "Something went wrong";
}
