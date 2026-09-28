import { FormEvent, type ReactNode, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { adminApi, auth } from "./api/client";
import { defaultHome, hasAnyPermission, isSuperAdmin } from "./auth/access";
import AppShell, { AppUser } from "./components/AppShell";
import AuthCard from "./components/AuthCard";
import AcceptInvitePage from "./pages/AcceptInvitePage";
import AdminPage from "./pages/AdminPage";
import AiConfigPage from "./pages/AiConfigPage";
import AuditPage from "./pages/AuditPage";
import ChatPage from "./pages/ChatPage";
import DocumentsPage from "./pages/DocumentsPage";
import FoldersPage from "./pages/FoldersPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import PlatformAuditPage from "./pages/PlatformAuditPage";
import PlatformConfigPage from "./pages/PlatformConfigPage";
import PlatformDashboardPage from "./pages/PlatformDashboardPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import RolesPage from "./pages/RolesPage";
import SourcesPage from "./pages/SourcesPage";
import TenantsPage from "./pages/TenantsPage";
import UsersPage from "./pages/UsersPage";

const PUBLIC_AUTH = ["/invite", "/reset", "/forgot-password"];

export default function App() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [publicSignup, setPublicSignup] = useState(false);
  const [error, setError] = useState("");
  const [user, setUser] = useState<AppUser | null>(null);
  const [bootstrapped, setBootstrapped] = useState(!localStorage.getItem("access_token"));
  const navigate = useNavigate();
  const location = useLocation();

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

  useEffect(() => {
    if (!localStorage.getItem("access_token")) return;
    auth
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setBootstrapped(true));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const tokens =
        mode === "signup"
          ? await auth.signup(email, password, tenantName)
          : await auth.login(email, password, tenantSlug.trim() || undefined);
      localStorage.setItem("access_token", tokens.access_token);
      localStorage.setItem("refresh_token", tokens.refresh_token);
      const me = await auth.me();
      setUser(me);
      navigate(defaultHome(me));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Auth failed");
    }
  }

  async function logout() {
    const refresh = localStorage.getItem("refresh_token");
    try {
      if (refresh) await auth.logout(refresh);
    } catch {
      /* token already invalid */
    }
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
    navigate("/");
  }

  if (PUBLIC_AUTH.includes(location.pathname)) {
    return (
      <Routes>
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset" element={<ResetPasswordPage />} />
        <Route path="/invite" element={<AcceptInvitePage />} />
      </Routes>
    );
  }

  if (!bootstrapped) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-body-md text-on-variant">
        Loading…
      </div>
    );
  }

  if (!user) {
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
            <label className="block text-left">
              <span className="field-label">Tenant ID</span>
              <input
                className="input-field mt-1.5"
                placeholder="Leave empty for Super Admin"
                value={tenantSlug}
                onChange={(e) => setTenantSlug(e.target.value)}
                autoComplete="off"
              />
              <span className="field-help">Leave empty for Super Admin sign-in. Tenant slug is required for company accounts.</span>
            </label>
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
            />
          </label>
          <label className="block text-left">
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
              />
              <button
                className="absolute right-2 top-1/2 -translate-y-1/2 text-label-sm text-secondary"
                type="button"
                onClick={() => setShowPassword((v) => !v)}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
            <span className="mt-1 flex items-center justify-between text-body-sm text-on-variant">
              <span>{mode === "signup" ? "Minimum 10 characters" : ""}</span>
              {mode === "login" && (
                <Link className="text-secondary hover:text-on-surface" to="/forgot-password">
                  Forgot password
                </Link>
              )}
            </span>
          </label>
          <div className="flex items-center justify-between rounded-lg bg-surface-low px-2.5 py-2.5">
            <span className="flex items-center gap-2 text-label-sm font-medium text-on-surface">
              <span className="status-dot h-2 w-2" />
              Isolation
            </span>
            <span className="rounded bg-surface-lowest px-2 py-0.5 font-mono text-code-sm text-secondary shadow-sm">
              Local Postgres
            </span>
          </div>
          <button className="btn btn-primary h-10 w-full" type="submit">
            {mode === "signup" ? "Create tenant" : "Sign in"}
          </button>
          {publicSignup && (
            <button
              className="w-full text-center text-body-sm text-on-variant"
              type="button"
              onClick={() => setMode(mode === "signup" ? "login" : "signup")}
            >
              {mode === "signup" ? (
                <>
                  Already have an account? <span className="font-medium text-on-surface underline underline-offset-2">Sign in</span>
                </>
              ) : (
                <>
                  Need a new tenant? <span className="font-medium text-on-surface underline underline-offset-2">Create tenant</span>
                </>
              )}
            </button>
          )}
        </form>
      </AuthCard>
    );
  }

  const home = defaultHome(user);

  return (
    <AppShell user={user} onLogout={logout}>
      <Routes>
        <Route
          path="/"
          element={
            isSuperAdmin(user) ? (
              <Navigate to="/platform" replace />
            ) : (
              <PermRoute user={user} anyOf={["ai.chat", "document:read", "conversation:read"]}>
                <ChatPage />
              </PermRoute>
            )
          }
        />
        <Route
          path="/data"
          element={
            <PermRoute user={user} anyOf={["folders.view", "document:read"]}>
              <FoldersPage />
            </PermRoute>
          }
        />
        <Route
          path="/documents"
          element={
            <PermRoute user={user} anyOf={["document:read", "document:write"]}>
              <DocumentsPage />
            </PermRoute>
          }
        />
        <Route
          path="/sources"
          element={
            <PermRoute user={user} anyOf={["source:manage"]}>
              <SourcesPage />
            </PermRoute>
          }
        />
        <Route
          path="/admin/users"
          element={
            <PermRoute user={user} anyOf={["users.view", "user:manage"]}>
              <UsersPage />
            </PermRoute>
          }
        />
        <Route
          path="/admin/roles"
          element={
            <PermRoute user={user} anyOf={["roles.view", "user:manage"]}>
              <RolesPage />
            </PermRoute>
          }
        />
        <Route
          path="/admin/ai"
          element={
            <PermRoute user={user} anyOf={["ai.configuration.view", "config:write", "config:read"]}>
              <AiConfigPage />
            </PermRoute>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <PermRoute user={user} anyOf={["audit.view", "audit:read"]}>
              <AuditPage />
            </PermRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <PermRoute user={user} anyOf={["config:read"]}>
              <AdminPage />
            </PermRoute>
          }
        />
        <Route
          path="/platform"
          element={
            <SuperOnly user={user}>
              <PlatformDashboardPage />
            </SuperOnly>
          }
        />
        <Route
          path="/platform/tenants"
          element={
            <SuperOnly user={user}>
              <TenantsPage />
            </SuperOnly>
          }
        />
        <Route
          path="/platform/config"
          element={
            <SuperOnly user={user}>
              <PlatformConfigPage />
            </SuperOnly>
          }
        />
        <Route
          path="/platform/audit"
          element={
            <SuperOnly user={user}>
              <PlatformAuditPage />
            </SuperOnly>
          }
        />
        <Route path="*" element={home ? <Navigate to={home} replace /> : <AccessDenied />} />
      </Routes>
    </AppShell>
  );
}

function SuperOnly({ user, children }: { user: AppUser; children: ReactNode }) {
  if (isSuperAdmin(user)) return children;
  const home = defaultHome(user);
  if (!home) return <AccessDenied />;
  return <Navigate to={home} replace />;
}

function PermRoute({ user, anyOf, children }: { user: AppUser; anyOf: string[]; children: ReactNode }) {
  if (isSuperAdmin(user) || hasAnyPermission(user, anyOf)) return children;
  const home = defaultHome(user);
  if (!home) return <AccessDenied />;
  return <Navigate to={home} replace />;
}

function AccessDenied() {
  return (
    <section className="panel px-6 py-10 text-center">
      <h1 className="text-headline-md">No access</h1>
      <p className="page-sub">Your account does not have permission to open this page.</p>
    </section>
  );
}
