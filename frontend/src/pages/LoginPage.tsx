import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorBanner, Field, inputClass } from "../components/ui";

export function LoginPage() {
  const { signIn } = useAuth();
  const [createAccount, setCreateAccount] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password, createAccount);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-full place-items-center px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-indigo-600 text-2xl text-white">✓</div>
          <h1 className="text-2xl font-bold text-slate-900">CiteSure</h1>
          <p className="text-sm text-slate-500">Answers you can verify.</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <Field label="Email">
            <input className={inputClass} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <input
              className={inputClass}
              type="password"
              autoComplete={createAccount ? "new-password" : "current-password"}
              required
              minLength={createAccount ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <ErrorBanner error={error} />
          <Button type="submit" className="w-full" disabled={busy}>
            {createAccount ? "Create account" : "Sign in"}
          </Button>
          <button type="button" className="w-full text-center text-sm text-indigo-700 hover:underline" onClick={() => setCreateAccount((v) => !v)}>
            {createAccount ? "I already have an account" : "Create an account"}
          </button>
        </form>
        <p className="text-center text-xs text-slate-400">Demo logins are listed in the README (employee@acme.example, hr@acme.example).</p>
      </div>
    </div>
  );
}
