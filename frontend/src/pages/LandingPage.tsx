import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { adminApi, auth } from "../api/client";
import AuthCard from "../components/AuthCard";

type LandingPageProps = {
  onLogin: (email: string, password: string, tenantSlug: string) => Promise<void>;
  onSignup: (email: string, password: string, tenantName: string) => Promise<void>;
};

export default function LandingPage({ onLogin, onSignup }: LandingPageProps) {
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [publicSignup, setPublicSignup] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(location.search).get("slug");
    if (q) setTenantSlug(q.trim().toLowerCase());
  }, [location.search]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const features = await auth.features();
        if (!cancelled && features?.public_signup) {
          setPublicSignup(true);
          return;
        }
      } catch {
        /* features endpoint may be missing */
      }
      try {
        const health = await adminApi.health();
        if (!cancelled && health?.public_signup) setPublicSignup(true);
      } catch {
        /* hide signup when the flag is absent */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setPending(true);
    try {
      if (mode === "signup") await onSignup(email, password, tenantName);
      else await onLogin(email, password, tenantSlug);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Auth failed");
      setPending(false);
    }
  }

  return (
    <AuthCard
      title="RAG Platform"
      subtitle={
        publicSignup && mode === "signup"
          ? "Create a tenant for your self-hosted knowledge cluster."
          : "Sign in with your tenant ID, email, and password. Super Admin may leave Tenant ID empty."
      }
    >
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        {error && <div className="banner-error">{error}</div>}
        {mode === "signup" ? (
          <label className="block text-left">
            <span className="field-label">Tenant Organization</span>
            <input
              className="input-field mt-1.5"
              placeholder="e.g. Acme Corp"
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              required
            />
          </label>
        ) : (
          <div className="block text-left">
            <label className="block">
              <span className="field-label">Tenant ID</span>
              <input
                className="input-field mt-1.5"
                placeholder="Leave empty for Super Admin"
                value={tenantSlug}
                onChange={(e) => setTenantSlug(e.target.value)}
                autoComplete="off"
              />
            </label>
            <span className="field-help">
              Leave empty for Super Admin sign-in. Tenant users enter the company slug and the password they set on
              the invite page — there is no shared default password.
            </span>
          </div>
        )}
        <label className="block text-left">
          <span className="field-label">Email</span>
          <input
            className="input-field mt-1.5"
            placeholder="you@example.com"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="username"
          />
        </label>
        <div className="block text-left">
          <label className="block">
            <span className="field-label">Password</span>
            <span className="relative mt-1.5 block">
              <input
                className="input-field pr-16"
                type={showPassword ? "text" : "password"}
                placeholder={mode === "signup" ? "10+ characters" : "Your password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === "signup" ? 10 : undefined}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
              <button
                className="absolute right-2 top-1/2 -translate-y-1/2 text-label-sm text-secondary"
                type="button"
                onClick={() => setShowPassword((v) => !v)}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
          </label>
          <span className="mt-1 flex items-center justify-between text-body-sm text-on-variant">
            <span>{mode === "signup" ? "Minimum 10 characters" : ""}</span>
            {mode === "login" && (
              <Link className="text-secondary hover:text-on-surface" to="/forgot-password">
                Forgot password
              </Link>
            )}
          </span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-surface-low px-2.5 py-2.5">
          <span className="flex items-center gap-2 text-label-sm font-medium text-on-surface">
            <span className="status-dot h-2 w-2" />
            Isolation
          </span>
          <span className="rounded bg-surface-lowest px-2 py-0.5 font-mono text-code-sm text-secondary shadow-sm">
            Local Postgres
          </span>
        </div>
        <button className="btn btn-primary h-10 w-full" type="submit" disabled={pending}>
          {pending ? "Signing in…" : mode === "signup" ? "Create tenant" : "Sign in"}
        </button>
        {publicSignup && (
          <button
            className="w-full text-center text-body-sm text-on-variant"
            type="button"
            onClick={() => {
              setMode(mode === "signup" ? "login" : "signup");
              setError("");
            }}
          >
            {mode === "signup" ? (
              <>
                Already have an account?{" "}
                <span className="font-medium text-on-surface underline underline-offset-2">Sign in</span>
              </>
            ) : (
              <>
                Need a new tenant?{" "}
                <span className="font-medium text-on-surface underline underline-offset-2">Create tenant</span>
              </>
            )}
          </button>
        )}
      </form>
    </AuthCard>
  );
}
