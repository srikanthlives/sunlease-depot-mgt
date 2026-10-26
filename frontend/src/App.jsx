import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import MainLayout from "./layouts/MainLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Locations from "./pages/Locations";
import Vehicles from "./pages/Vehicles";
import RoutesPage from "./pages/Routes";
import Availability from "./pages/Availability";
import DutyDay from "./pages/DutyDay";
import DutyPatterns from "./pages/DutyPatterns";
import DutyStats from "./pages/DutyStats";
import Rosters from "./pages/Rosters";
import Employees from "./pages/Employees";
import Schedules from "./pages/Schedules";
import ScheduleBuilder from "./pages/ScheduleBuilder";
import ScheduleViewer from "./pages/ScheduleViewer";
import PrintTimetable from "./pages/PrintTimetable";
import Users from "./pages/Users";
import SettingsPage from "./pages/Settings";
import AuditLog from "./pages/AuditLog";
import Organisation from "./pages/Organisation";
import TripSheets from "./pages/TripSheets";
import TripReasons from "./pages/TripReasons";
import TripSheet from "./pages/TripSheet";
import PrintTripSheet from "./pages/PrintTripSheet";
import { BillingReport, CrewHours, MissingSheets } from "./pages/Reports";

/** `allow(auth)` gates the page; omitted = any signed-in user. */
function Protected({ children, allow }) {
  const auth = useAuth();
  if (!auth.user) return <Navigate to="/login" replace />;
  if (allow && !allow(auth)) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/print/:versionId" element={<Protected><PrintTimetable /></Protected>} />
            <Route path="/print-sheets" element={<Protected><PrintTripSheet /></Protected>} />
            <Route element={<Protected><MainLayout /></Protected>}>
              <Route index element={<Dashboard />} />
              <Route path="locations" element={<Locations />} />
              <Route path="vehicles" element={<Vehicles />} />
              <Route path="routes" element={<RoutesPage />} />
              <Route path="routes/:routeId" element={<RoutesPage />} />
              <Route path="employees" element={<Employees />} />
              <Route path="rosters" element={<Rosters />} />
              <Route path="duty-day" element={<DutyDay />} />
              <Route path="duty-patterns" element={<DutyPatterns />} />
              <Route path="reports/duty-statistics" element={<DutyStats />} />
              <Route path="availability" element={<Availability />} />
              <Route path="trip-reasons" element={<TripReasons />} />
              <Route path="schedules" element={<Schedules />} />
              <Route path="schedules/:scheduleId" element={<ScheduleBuilder />} />
              <Route path="schedules/:scheduleId/v/:versionId" element={<ScheduleBuilder />} />
              <Route path="viewer" element={<ScheduleViewer />} />
              <Route path="trip-sheets" element={<TripSheets />} />
              <Route path="trip-sheets/:sheetId" element={<TripSheet />} />
              <Route path="reports/billing" element={<BillingReport />} />
              <Route path="reports/missing-sheets" element={<MissingSheets />} />
              <Route path="reports/crew-hours" element={<CrewHours />} />
              <Route path="users" element={<Protected allow={(a) => a.isSuper}><Users /></Protected>} />
              <Route path="organisation" element={<Protected allow={(a) => a.isSuper}><Organisation /></Protected>} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="audit" element={<Protected allow={(a) => a.adminAnywhere}><AuditLog /></Protected>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
