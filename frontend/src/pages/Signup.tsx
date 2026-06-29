import { FormEvent, useState } from "react";
import { Lock, Mail, UserPlus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { AuthResponse, apiFetch, setAuth } from "../lib/api";

export default function Signup() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const auth = await apiFetch<AuthResponse>("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setAuth(auth);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-cloud-ink px-4 py-10 text-slate-100">
      <form onSubmit={submit} className="w-full max-w-md rounded-lg border border-cloud-line bg-cloud-panel p-6 shadow-2xl">
        <div className="mb-6">
          <p className="text-sm font-medium uppercase text-cloud-orange">Cloud Cost Detective</p>
          <h1 className="mt-2 text-2xl font-semibold text-white">Create account</h1>
        </div>
        <label className="mb-4 block text-sm font-medium text-slate-300">
          Email
          <span className="mt-2 flex items-center gap-2 rounded-md border border-cloud-line bg-cloud-ink px-3 focus-within:border-cloud-orange">
            <Mail className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <input
              className="h-11 w-full bg-transparent text-white outline-none"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </span>
        </label>
        <label className="mb-5 block text-sm font-medium text-slate-300">
          Password
          <span className="mt-2 flex items-center gap-2 rounded-md border border-cloud-line bg-cloud-ink px-3 focus-within:border-cloud-orange">
            <Lock className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <input
              className="h-11 w-full bg-transparent text-white outline-none"
              type="password"
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </span>
        </label>
        {error && <p className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-cloud-orange px-4 font-semibold text-slate-950 hover:bg-orange-300 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <UserPlus className="h-4 w-4" aria-hidden="true" />
          {loading ? "Creating" : "Create account"}
        </button>
        <p className="mt-5 text-center text-sm text-slate-400">
          Have an account? <Link className="font-medium text-cloud-cyan hover:text-teal-200" to="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}