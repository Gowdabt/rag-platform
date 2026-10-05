import { type ReactNode, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { auth } from "./api/client";
import { defaultHome, hasAnyPermission, isSuperAdmin } from "./auth/access";
import { CurrentUserContext } from "./auth/CurrentUserContext";
import AppShell, { AppUser } from "./components/AppShell";
import AcceptInvitePage from "./pages/AcceptInvitePage";
import AdminPage from "./pages/AdminPage";
import AiConfigPage from "./pages/AiConfigPage";
import AuditPage from "./pages/AuditPage";
import ChatPage from "./pages/ChatPage";
import DocumentsPage from "./pages/DocumentsPage";
import FoldersPage from "./pages/FoldersPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import HomePage from "./pages/HomePage";
import LandingPage from "./pages/LandingPage";
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
  const [user, setUser] = useState<AppUser | null>(null);
  const [bootstrapped, setBootstrapped] = useState(!localStorage.getItem("access_token"));
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!localStorage.getItem("access_token")) return;
    auth
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setBootstrapped(true));
  }, []);

  async function establishSession(tokens: { access_token: string; refresh_token: string }) {
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
    localStorage.removeItem("active_conversation_id");
    const me = await auth.me();
    setUser(me);
    navigate(defaultHome(me));
  }

  async function onLogin(email: string, password: string, tenantSlug: string) {
    const tokens = await auth.login(email, password, tenantSlug.trim().toLowerCase() || undefined);
    await establishSession(tokens);
  }

  async function onSignup(email: string, password: string, tenantName: string) {
    const tokens = await auth.signup(email, password, tenantName);
    await establishSession(tokens);
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
    localStorage.removeItem("active_conversation_id");
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
    return <LandingPage onLogin={onLogin} onSignup={onSignup} />;
  }

  const home = defaultHome(user);

  return (
    <CurrentUserContext.Provider value={user}>
    <AppShell user={user} onLogout={logout}>
      <Routes>
        <Route
          path="/home"
          element={
            <PermRoute user={user} anyOf={["ai.chat", "document:read", "conversation:read", "document:write"]}>
              <HomePage />
            </PermRoute>
          }
        />
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
    </CurrentUserContext.Provider>
  );
}

function SuperOnly({ user, children }: { user: AppUser; children: ReactNode }) {
  if (isSuperAdmin(user)) return children;
  const home = defaultHome(user);
  if (!home) return <AccessDenied />;
  return <Navigate to={home} replace />;
}

function PermRoute({ user, anyOf, children }: { user: AppUser; anyOf: string[]; children: ReactNode }) {
  if (isSuperAdmin(user)) {
    const home = defaultHome(user);
    if (!home) return <AccessDenied />;
    return <Navigate to={home} replace />;
  }
  if (hasAnyPermission(user, anyOf)) return children;
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
