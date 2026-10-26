import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ClipboardList } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiErrorMessage } from "../api/client";
import { Button } from "../components/ui";
import { TextInput } from "../components/inputs";
import { useFormKeys } from "../lib/keys";

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ username: "", password: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const keys = useFormKeys({ onSave: () => submit() });
  if (user) return <Navigate to="/" replace />;
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await login(f.username, f.password);
      nav("/");
    } catch (e) {
      setErr(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-ink to-brand-700 p-4">
      <form className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow-2xl" onSubmit={(e) => { e.preventDefault(); submit(); }}
        onKeyDown={keys}>
        <div className="flex items-center gap-2">
          <ClipboardList className="h-6 w-6 text-brand-600" />
          <div>
            <h1 className="font-semibold text-ink">Sunlease Depot Management</h1>
            <p className="text-xs text-slate-500">Fixed bus schedules</p>
          </div>
        </div>
        <TextInput label="Username" autoFocus value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        <TextInput label="Password" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        {err && <p className="text-sm text-danger">{err}</p>}
        <Button type="submit" className="w-full" loading={busy}>Sign in</Button>
      </form>
    </div>
  );
}
