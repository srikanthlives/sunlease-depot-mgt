// Date/time parsing and formatting. UI format: DD-MMM-YYYY (e.g. 21-Oct-2026),
// 24-hour HH:MM times. The API always speaks ISO (YYYY-MM-DD, HH:MM).

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const pad = (n) => String(n).padStart(2, "0");

export function isoFromParts(y, m, d) {
  return `${y}-${pad(m)}-${pad(d)}`;
}

export function todayIso(now = new Date()) {
  return isoFromParts(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

function validDate(y, m, d) {
  if (m < 1 || m > 12 || d < 1) return false;
  const dim = new Date(y, m, 0).getDate();
  return d <= dim;
}

export function addDays(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + n);
  return isoFromParts(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
}

/** ISO -> "21-Oct-2026". Empty for null. */
export function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  return `${pad(d)}-${MONTHS[m - 1]}-${y}`;
}

/** "21-Oct-2026" + weekday, for read-only views. */
export function fmtDateLong(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(y, m - 1, d).toLocaleDateString("en-GB", { weekday: "short" });
  return `${wd} ${fmtDate(iso)}`;
}

/**
 * Parse what a user typed into a date field. Returns {iso} or {error}, or {iso:null} for blank.
 * Accepts: 21-Oct-2026, 21-oct-26, 21 Oct, 21-10-2026, 21/10/26, 21102026, 211026, 2110, 21,
 * 2026-10-21 (ISO), T / today, +N / -N (relative to `base` or today).
 */
export function parseDate(input, { base, now = new Date() } = {}) {
  const s = String(input ?? "").trim();
  if (!s) return { iso: null };
  const today = todayIso(now);
  const cy = now.getFullYear();
  const cm = now.getMonth() + 1;
  const lower = s.toLowerCase();
  if (lower === "t" || lower === "today") return { iso: today };
  const rel = /^([+-])(\d{1,4})$/.exec(s);
  if (rel) return { iso: addDays(base || today, (rel[1] === "-" ? -1 : 1) * Number(rel[2])) };

  const year = (y) => {
    if (y === undefined || y === "") return cy;
    const n = Number(y);
    return y.length <= 2 ? 2000 + n : n;
  };
  let y, m, d;
  let mm;
  if ((mm = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s))) {
    [y, m, d] = [Number(mm[1]), Number(mm[2]), Number(mm[3])];
  } else if ((mm = /^(\d{1,2})[\s\-/.]*([a-z]{3,9})(?:[\s\-/.,]*(\d{2}|\d{4}))?$/i.exec(s))) {
    const idx = MONTHS.findIndex((x) => mm[2].toLowerCase().startsWith(x.toLowerCase()));
    if (idx < 0) return { error: `Unknown month "${mm[2]}"` };
    [d, m, y] = [Number(mm[1]), idx + 1, year(mm[3])];
  } else if ((mm = /^(\d{1,2})[\-/.](\d{1,2})(?:[\-/.](\d{2}|\d{4}))?$/.exec(s))) {
    [d, m, y] = [Number(mm[1]), Number(mm[2]), year(mm[3])];
  } else if (/^\d+$/.test(s)) {
    if (s.length <= 2) [d, m, y] = [Number(s), cm, cy];
    else if (s.length === 4) [d, m, y] = [Number(s.slice(0, 2)), Number(s.slice(2)), cy];
    else if (s.length === 6) [d, m, y] = [Number(s.slice(0, 2)), Number(s.slice(2, 4)), year(s.slice(4))];
    else if (s.length === 8) [d, m, y] = [Number(s.slice(0, 2)), Number(s.slice(2, 4)), Number(s.slice(4))];
    else return { error: "Use DD-MMM-YYYY" };
  } else {
    return { error: "Use DD-MMM-YYYY" };
  }
  if (!validDate(y, m, d)) return { error: `${pad(d)}-${MONTHS[m - 1] || pad(m)}-${y} is not a valid date` };
  return { iso: isoFromParts(y, m, d) };
}

/**
 * Parse a typed time. Returns {time:"HH:MM"} | {time:null} | {error}.
 * Accepts 930, 0930, 9:30, 09.30, 9, 22, 2230, 22:30.
 */
export function parseTime(input) {
  const s = String(input ?? "").trim();
  if (!s) return { time: null };
  let h, m;
  let mm;
  if ((mm = /^(\d{1,2})[:.\s](\d{1,2})$/.exec(s))) [h, m] = [Number(mm[1]), Number(mm[2])];
  else if (/^\d{1,2}$/.test(s)) [h, m] = [Number(s), 0];
  else if (/^\d{3,4}$/.test(s)) [h, m] = [Number(s.slice(0, s.length - 2)), Number(s.slice(-2))];
  else return { error: "Use 24-hour HH:MM" };
  if (h > 23 || m > 59) return { error: "Use 24-hour HH:MM (00:00 - 23:59)" };
  return { time: `${pad(h)}:${pad(m)}` };
}

export const toMin = (hhmm) => {
  if (!hhmm) return null;
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

/** minutes since operating-date midnight, from day offset + HH:MM */
export const relMin = (offset, hhmm) => (hhmm ? (Number(offset) || 0) * 1440 + toMin(hhmm) : null);

export function fmtDuration(min) {
  if (min === null || min === undefined || Number.isNaN(min)) return "";
  const sign = min < 0 ? "-" : "";
  const a = Math.abs(min);
  const h = Math.floor(a / 60);
  const m = a % 60;
  return h ? `${sign}${h}h ${pad(m)}m` : `${sign}${m}m`;
}

/** relative minutes -> "HH:MM" plus day tag (+1) */
export function fmtRel(min) {
  if (min === null || min === undefined) return "";
  const day = Math.floor(min / 1440);
  const r = min - day * 1440;
  return `${pad(Math.floor(r / 60))}:${pad(r % 60)}${day ? ` +${day}` : ""}`;
}

export const fmtKm = (v) => (v === null || v === undefined || v === "" ? "" : `${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })} km`);
export const num = (v) => (v === null || v === undefined || v === "" ? null : Number(v));

export const LABELS = {
  PASSENGER_TRIP: "Passenger trip", NON_REVENUE_MOVEMENT: "Movement", CHARGING: "Charging", LAYOVER: "Layover", HALT: "Halt",
  DEPOT_POSITIONING: "Depot positioning", CHARGING_ACCESS: "Charging access", RETURN_TO_SERVICE: "Return to service",
  RETURN_TO_DEPOT: "Return to depot", MAINTENANCE: "Maintenance", OTHER: "Other",
  PAYABLE: "Payable", NON_PAYABLE: "Non-payable", TO_BE_CONFIRMED: "To be confirmed",
  PER_KM: "Per km", FIXED_AMOUNT: "Fixed amount", INCLUDED_IN_CONTRACT: "Included in contract", UNSPECIFIED: "Unspecified",
  TERMINAL_RECOVERY: "Terminal recovery", INTER_TRIP: "Inter-trip layover", OVERNIGHT_PARKING: "Overnight parking",
  DEPOT: "Depot", TERMINAL: "Terminal", BUS_STOP: "Bus stop", CHARGING_POINT: "Charging point",
  DRIVER: "Driver", CONDUCTOR: "Conductor", DEPOT_STAFF: "Depot staff",
  ACTIVE: "Active", INACTIVE: "Inactive", RETIRED: "Retired", DRAFT: "Draft", PUBLISHED: "Published", SUPERSEDED: "Superseded",
  ADMIN: "Admin", PUBLISHER: "Publisher", SCHEDULER: "Scheduler", MIS: "MIS / Clerk", VIEWER: "Viewer",
  SINGLE: "One driver for the day", SHIFTS: "Shifts",
  PENDING: "Not entered", OPERATED: "Operated", PARTIAL: "Cut short", CANCELLED: "Cancelled",
  NOT_STARTED: "Not started", SUBMITTED: "Submitted", APPROVED: "Approved",
  OPERATOR: "Operator", CLIENT: "Client", EXTERNAL: "External (traffic, road, weather)",
  SCHEDULED: "Scheduled", LIVE: "Live", ENDED: "Ended",
  WEEKLY_OFF: "Weekly off", LEAVE: "Leave", SICK: "Sick", TRAINING: "Training",
  AS_PLANNED: "As planned", REPLACED: "Replaced", ABSENT: "Nobody worked it", NOT_OPERATED: "Not operated",
  GENERATED: "From pattern", MANUAL: "By hand", CARRIED: "Carried over",
  SPARE: "Spare", SHUNTING: "Shunting", SCHEDULE: "Bus duty",
  ADDED: "Added", REMOVED: "Removed",
  HANDED_OVER: "Handed over part-way", TOOK_OVER: "Took over mid-duty",
};
export const label = (v) => LABELS[v] || v;
export const options = (values) => values.map((v) => ({ value: v, label: label(v) }));
