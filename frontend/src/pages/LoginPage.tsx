import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { Icon, Logo, type IconName } from "../components/Icon";
import { Button, ErrorBanner, Field, inputClass } from "../components/ui";

const POINTS: { icon: IconName; text: string }[] = [
  { icon: "quote", text: "Every sentence links to the exact passage it came from" },
  { icon: "shield", text: "Claims the sources do not support are removed, not guessed" },
  { icon: "lock", text: "You only ever see answers from documents you may read" },
];

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
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative isolate hidden overflow-hidden bg-slate-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(70% 60% at 20% 10%, rgb(79 70 229 / 0.55), transparent 70%), radial-gradient(60% 50% at 90% 80%, rgb(14 165 233 / 0.4), transparent 70%), radial-gradient(40% 40% at 60% 40%, rgb(168 85 247 / 0.3), transparent 70%)",
          }}
        />
        <div className="flex items-center gap-3 text-xl font-bold">
          <Logo className="h-10 w-10" />
          CiteSure
        </div>
        <div>
          <h2 className="max-w-md text-4xl font-extrabold leading-tight tracking-tight">Answers you can check, not just trust.</h2>
          <ul className="mt-8 space-y-4">
            {POINTS.map((point) => (
              <li key={point.text} className="flex items-start gap-3 text-slate-200">
                <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white/10 ring-1 ring-white/15">
                  <Icon name={point.icon} className="h-4 w-4" />
                </span>
                {point.text}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-sm text-slate-400">Your documents stay on your system.</p>
      </section>

      <div className="relative isolate grid place-items-center px-4 py-10">
        <div className="aurora absolute inset-0 -z-10 lg:hidden" aria-hidden="true" />
        <div className="w-full max-w-sm space-y-6">
          <div className="text-center">
            <div className="mx-auto mb-3 flex justify-center lg:hidden">
              <Logo className="h-12 w-12" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">{createAccount ? "Create your account" : "Welcome back"}</h1>
            <p className="mt-1 text-sm text-slate-500">{createAccount ? "It takes a few seconds." : "Sign in to CiteSure. Answers you can verify."}</p>
          </div>
          <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-soft">
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
            <Button type="submit" className="w-full py-2.5" disabled={busy}>
              {createAccount ? "Create account" : "Sign in"}
            </Button>
            <button type="button" className="w-full text-center text-sm font-medium text-indigo-700 hover:underline" onClick={() => setCreateAccount((v) => !v)}>
              {createAccount ? "I already have an account" : "Create an account"}
            </button>
          </form>
          <p className="text-center text-xs text-slate-400">Demo logins are listed in the README (employee@acme.example, hr@acme.example).</p>
        </div>
      </div>
    </div>
  );
}
