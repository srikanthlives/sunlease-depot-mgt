import { NavLink, Outlet } from "react-router-dom";
import { BarChart3, Building2, BusFront, CalendarCheck, CalendarClock, CalendarOff, CalendarRange, Repeat2, ClipboardCheck, ClipboardList, Eye, FileWarning, Gauge, History, IndianRupee, Layers, ListChecks, LogOut, MapPin, Route, Settings, Timer, UserSquare2, Users } from "lucide-react";
import clsx from "clsx";
import { ALL, useAuth } from "../context/AuthContext";
import { Empty, ShortcutHelp } from "../components/ui";
import { label } from "../lib/format";

// show(auth) decides visibility; omitted = everyone
const NAV = [
  { group: "Operations", items: [
    { to: "/", label: "Overview", icon: Gauge, end: true },
    { to: "/schedules", label: "Schedules", icon: CalendarClock },
    { to: "/viewer", label: "Schedule viewer", icon: Eye },
    { to: "/rosters", label: "Duty roster", icon: CalendarRange },
    { to: "/duty-day", label: "Duty day", icon: CalendarCheck },
    { to: "/trip-sheets", label: "Trip sheets", icon: ClipboardCheck },
  ] },
  { group: "Reports", items: [
    { to: "/reports/billing", label: "Billing", icon: IndianRupee },
    { to: "/reports/missing-sheets", label: "Missing sheets", icon: FileWarning },
    { to: "/reports/crew-hours", label: "Crew hours", icon: Timer },
    { to: "/reports/duty-statistics", label: "Duty statistics", icon: BarChart3 },
  ] },
  { group: "Masters", items: [
    { to: "/routes", label: "Routes", icon: Route },
    { to: "/locations", label: "Locations", icon: MapPin },
    { to: "/vehicles", label: "Vehicles", icon: BusFront },
    { to: "/employees", label: "Employees", icon: UserSquare2 },
    { to: "/availability", label: "Availability", icon: CalendarOff },
    { to: "/duty-patterns", label: "Duty patterns", icon: Repeat2 },
    { to: "/trip-reasons", label: "Reason codes", icon: ListChecks },
  ] },
  { group: "Admin", items: [
    { to: "/settings", label: "Validation settings", icon: Settings },
    { to: "/audit", label: "Audit log", icon: History, show: (a) => a.adminAnywhere },
    { to: "/organisation", label: "Organisation", icon: Building2, show: (a) => a.isSuper },
    { to: "/users", label: "Users", icon: Users, show: (a) => a.isSuper },
  ] },
];

/** Cost-center switcher: the user's cost centers grouped by company, plus the read-only All view. */
function CostCenterSwitcher() {
  const { costCenters, cc, setCc } = useAuth();
  if (!costCenters.length) return null;
  const companies = [...new Map(costCenters.map((m) => [m.company_id, m.company_name])).entries()];
  return (
    <label className="flex items-center gap-1.5 text-sm">
      <Layers className="h-4 w-4 text-brand-300" />
      <span className="sr-only">Cost center</span>
      <select value={cc || ""} onChange={(e) => setCc(e.target.value)} title="Switch cost center"
        className="max-w-[16rem] rounded-md border border-white/20 bg-white/10 py-1 pl-2 pr-7 text-sm text-white outline-none focus:ring-2 focus:ring-brand-300 [&>*]:text-ink">
        {costCenters.length > 1 && <option value={ALL}>All my cost centers</option>}
        {companies.map(([id, name]) => (
          <optgroup key={id} label={name}>
            {costCenters.filter((m) => m.company_id === id).map((m) => (
              <option key={m.cost_center_id} value={m.cost_center_id}>{m.cost_center_code} · {m.cost_center_name} ({label(m.role)})</option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

export default function MainLayout() {
  const auth = useAuth();
  const { user, logout, isSuper, costCenters, cc, current, isAll } = auth;
  const items = (g) => g.items.filter((i) => !i.show || i.show(auth));
  const roleText = isSuper ? "Super admin" : isAll ? "All my cost centers" : current ? label(current.role) : "";
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-12 items-center justify-between gap-3 bg-ink px-4 text-white print:hidden">
        <div className="flex min-w-0 items-center gap-2">
          <ClipboardList className="h-5 w-5 shrink-0 text-brand-300" />
          <span className="font-semibold">Sunlease</span>
          <span className="hidden text-sm text-brand-200 lg:inline">Depot Management</span>
        </div>
        <div className="flex min-w-0 items-center gap-3 text-sm">
          <CostCenterSwitcher />
          <ShortcutHelp />
          <span className="hidden whitespace-nowrap text-brand-100 sm:inline">{user?.full_name || user?.username} · {roleText}</span>
          <button onClick={logout} className="flex items-center gap-1 rounded-md px-2 py-1 text-brand-100 hover:bg-white/10" title="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>
      <div className="flex flex-1">
        <nav className="hidden w-52 shrink-0 border-r border-slate-200 bg-white p-3 md:block print:hidden">
          {NAV.map((g) => (
            <div key={g.group} className="mb-4">
              <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{g.group}</p>
              {items(g).map((i) => (
                <NavLink key={i.to} to={i.to} end={i.end}
                  className={({ isActive }) => clsx("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                    isActive ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-50")}>
                  <i.icon className="h-4 w-4" /> {i.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <nav className="mb-3 flex gap-1 overflow-x-auto md:hidden print:hidden">
            {NAV.flatMap(items).map((i) => (
              <NavLink key={i.to} to={i.to} end={i.end} className={({ isActive }) => clsx("whitespace-nowrap rounded-md px-2 py-1 text-xs", isActive ? "bg-brand-600 text-white" : "bg-white text-slate-600")}>{i.label}</NavLink>
            ))}
          </nav>
          {isAll && <p className="mb-3 rounded-md bg-brand-50 px-3 py-1.5 text-xs text-brand-800 print:hidden">Showing all your cost centers. Pick one cost center in the top bar to add records; existing records can still be opened and edited where your role allows.</p>}
          {!costCenters.length && !isSuper ? (
            <Empty icon={Layers} title="No cost center assigned">Ask a super admin to give you a role in a cost center.</Empty>
          ) : (
            // remount the page when the cost center changes, so every page reloads its data
            <Outlet key={cc || "none"} />
          )}
        </main>
      </div>
    </div>
  );
}
