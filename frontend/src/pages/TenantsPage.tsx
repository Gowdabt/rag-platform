import { FormEvent, useEffect, useState } from "react";
import { asList, platformApi } from "../api/client";
import Modal from "../components/Modal";
import StatusPill from "../components/StatusPill";
import { Alert, Metric, PageHeader } from "../components/ui";

type TenantRow = {
  id: string;
  name?: string;
  company_name?: string;
  slug?: string;
  status?: string;
  admin_email?: string;
  admin_name?: string;
  created_at?: string;
};

type SeededUser = {
  role: string;
  email: string;
  name?: string;
  status?: string;
  is_demo?: boolean;
  invitation_token?: string;
  invite_path?: string;
  invitation_expires_at?: string;
};

type SeededUserView = SeededUser & { inviteUrl?: string };

type CreatedInvite = {
  company: string;
  slug: string;
  adminEmail: string;
  token?: string;
  inviteUrl?: string;
  expiresAt?: string;
  passwordSet: boolean;
  message?: string;
  seededUsers: SeededUserView[];
};

function originInviteUrl(path?: string, token?: string): string | undefined {
  const resolved = path || (token ? `/invite?token=${token}` : "");
  return resolved ? `${window.location.origin}${resolved}` : undefined;
}

function roleKey(role: string): string {
  return role
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function slugifyTenantId(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 128);
}

export default function TenantsPage() {
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const [openCreate, setOpenCreate] = useState(false);
  const [view, setView] = useState<TenantRow | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const data = await platformApi.tenants();
    setTenants(asList<TenantRow>(data));
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load tenants"));
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    setPending(true);
    const password = adminPassword.trim();
    if (password && password.length < 10) {
      setError("Temporary admin password must be at least 10 characters, or leave it blank to use invite-only.");
      setPending(false);
      return;
    }
    try {
      const body: {
        name: string;
        slug: string;
        admin_name: string;
        admin_email: string;
        admin_password?: string;
      } = {
        name: companyName.trim(),
        slug: slugifyTenantId(slug) || slugifyTenantId(companyName),
        admin_name: adminName.trim(),
        admin_email: adminEmail.trim(),
      };
      if (password) body.admin_password = password;
      const result = await platformApi.createTenant(body);
      const tenant = result?.tenant || {};
      const token = result?.invitation_token || result?.invite_token;
      const path = result?.invite_path || (token ? `/invite?token=${token}` : "");
      const adminEmailResolved = result?.admin_email || body.admin_email;
      const rawSeeded: SeededUser[] = Array.isArray(result?.seeded_users) ? result.seeded_users : [];
      const seededUsers: SeededUserView[] = rawSeeded.length
        ? rawSeeded.map((row) => ({
            ...row,
            inviteUrl: originInviteUrl(row.invite_path, row.invitation_token),
          }))
        : [
            {
              role: "Tenant Admin",
              email: adminEmailResolved,
              is_demo: false,
              inviteUrl: originInviteUrl(path, token),
              invitation_expires_at: result?.invitation_expires_at,
            },
          ];
      setCreated({
        company: tenant.company_name || tenant.name || companyName.trim(),
        slug: result?.slug || tenant.slug || body.slug,
        adminEmail: adminEmailResolved,
        token,
        inviteUrl: path ? `${window.location.origin}${path}` : undefined,
        expiresAt: result?.invitation_expires_at,
        passwordSet: Boolean(result?.password_set),
        message: result?.message,
        seededUsers,
      });
      setOpenCreate(false);
      setCompanyName("");
      setSlug("");
      setSlugTouched(false);
      setAdminName("");
      setAdminEmail("");
      setAdminPassword("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create tenant");
    } finally {
      setPending(false);
    }
  }

  async function setStatus(id: string, status: "suspended" | "active") {
    setError("");
    try {
      await platformApi.patchTenant(id, { status });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update tenant");
    }
  }

  async function openView(row: TenantRow) {
    try {
      const detail = await platformApi.getTenant(row.id);
      setView({ ...row, ...(detail || {}) });
    } catch {
      setView(row);
    }
  }

  const active = tenants.filter((t) => (t.status || "active").toLowerCase() === "active").length;
  const suspended = tenants.filter((t) => (t.status || "").toLowerCase() === "suspended").length;

  return (
    <section className="space-y-5">
      <PageHeader
        title="Tenants"
        subtitle="Provision companies, suspend access, and copy invite tokens in development. Tenant Admins set their own password — there is no shared default."
        actions={
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              setError("");
              setSlugTouched(false);
              setOpenCreate(true);
            }}
          >
            + Create Tenant
          </button>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Metric label="Tenants" value={String(tenants.length)} />
        <Metric label="Active" value={String(active)} />
        <Metric label="Suspended" value={String(suspended)} />
      </div>
      {error && !openCreate && <Alert>{error}</Alert>}
      {created && <InvitePanel invite={created} onDismiss={() => setCreated(null)} />}
      <div className="panel">
        <div className="data-head cols-tenant">
          <span>Company</span>
          <span>Tenant ID</span>
          <span>Admin email</span>
          <span>Status</span>
          <span>Actions</span>
        </div>
        <ul>
          {tenants.map((t) => {
            const status = (t.status || "active").toLowerCase();
            const company = t.company_name || t.name || "—";
            const tenantId = t.slug || "—";
            return (
              <li key={t.id} className="data-row cols-tenant" data-testid="tenant-row" data-slug={tenantId}>
                <span className="min-w-0 truncate font-medium" data-testid="tenant-company">
                  {company}
                </span>
                <span className="min-w-0 truncate font-mono text-code-md text-on-variant" data-testid="tenant-slug">
                  {tenantId}
                </span>
                <span className="min-w-0 truncate text-on-variant" data-testid="tenant-admin">
                  {t.admin_email || "—"}
                </span>
                <span data-testid="tenant-status">
                  <StatusPill status={t.status || "active"} />
                </span>
                <div className="flex flex-wrap gap-3" data-testid="tenant-actions">
                  <button className="link-action" type="button" onClick={() => openView(t)}>
                    View
                  </button>
                  {status === "suspended" ? (
                    <button className="link-action" type="button" onClick={() => setStatus(t.id, "active")}>
                      Reactivate
                    </button>
                  ) : (
                    <button className="link-action" type="button" onClick={() => setStatus(t.id, "suspended")}>
                      Suspend
                    </button>
                  )}
                </div>
              </li>
            );
          })}
          {tenants.length === 0 && <li className="px-4 py-8 text-center text-body-md text-on-variant">No tenants yet.</li>}
        </ul>
      </div>

      {openCreate && (
        <Modal title="Create Tenant" onClose={() => setOpenCreate(false)}>
          <form className="mt-4 space-y-3 text-sm" onSubmit={onCreate}>
            {error && <Alert>{error}</Alert>}
            <p className="rounded-lg bg-surface-low px-3 py-2 text-[12px] leading-[18px] text-on-variant">
              This does not create a default password. The Tenant Admin cannot sign in until they choose a password on
              the invite page (or you set an optional temporary password below). Sign-in uses Tenant ID + email + that
              password.
            </p>
            <label className="block">
              Company name
              <input
                className="input-field mt-1"
                value={companyName}
                onChange={(e) => {
                  const next = e.target.value;
                  setCompanyName(next);
                  if (!slugTouched) setSlug(slugifyTenantId(next));
                }}
                required
              />
            </label>
            <label className="block">
              Tenant ID (slug)
              <input
                className="input-field mt-1 font-mono"
                value={slug}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value);
                }}
                onBlur={() => setSlug(slugifyTenantId(slug) || slug)}
                placeholder="acme"
                required
              />
              <span className="field-help">Lowercase letters, digits, and hyphens. “Salesforce” is stored as salesforce.</span>
            </label>
            <label className="block">
              Admin name
              <input className="input-field mt-1" value={adminName} onChange={(e) => setAdminName(e.target.value)} required />
            </label>
            <label className="block">
              Admin email
              <input
                className="input-field mt-1"
                type="email"
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                required
              />
            </label>
            <label className="block">
              Temporary admin password (optional)
              <input
                className="input-field mt-1"
                type="password"
                autoComplete="new-password"
                value={adminPassword}
                onChange={(e) => setAdminPassword(e.target.value)}
                minLength={10}
                placeholder="Leave blank for invite-only"
              />
              <span className="field-help">
                Optional. If set (10+ characters), the admin can sign in immediately with Tenant ID + email + this
                password. Otherwise they must open the invite link and choose a password. There is no platform-wide
                default password.
              </span>
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button className="btn btn-secondary" type="button" onClick={() => setOpenCreate(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" type="submit" disabled={pending}>
                {pending ? "Creating…" : "Create"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {view && (
        <Modal title={view.company_name || view.name || "Tenant"} onClose={() => setView(null)}>
          <dl className="mt-4 space-y-2 text-sm">
            <Row label="Company" value={view.company_name || view.name} />
            <Row label="Tenant ID" value={view.slug} />
            <Row label="Admin" value={[view.admin_name, view.admin_email].filter(Boolean).join(" · ")} />
            <Row label="Status" value={view.status || "active"} />
            <Row label="ID" value={view.id} />
          </dl>
        </Modal>
      )}
    </section>
  );
}

function InvitePanel({ invite, onDismiss }: { invite: CreatedInvite; onDismiss: () => void }) {
  return (
    <div className="panel space-y-3 p-4" data-testid="tenant-invite-panel">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-headline-sm">Tenant created — starter accounts</h2>
          <p className="mt-1 text-[13px] leading-[18px] text-on-variant">
            No default password is created. These are starter accounts; each person sets a password via their invite
            link. This is not a shared default password.
            {invite.passwordSet
              ? " A temporary password applies only to the Tenant Admin. Demo users stay invite-only."
              : " The Tenant Admin and demo users must open their invite links and choose a password, then sign in with Tenant ID + email + that password."}
          </p>
        </div>
        <button className="btn btn-ghost h-8 px-2" type="button" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
      <dl className="grid gap-2 text-sm md:grid-cols-2">
        <CopyRow label="Company" value={invite.company} />
        <CopyRow label="Tenant ID (slug)" value={invite.slug} testId="invite-slug" />
        {invite.expiresAt && <CopyRow label="Invite expires" value={formatExpiry(invite.expiresAt)} />}
      </dl>
      <div className="space-y-3" data-testid="seeded-users">
        {invite.seededUsers.map((user) => {
          const key = roleKey(user.role || "");
          const isAdmin = !user.is_demo;
          const url = user.inviteUrl;
          return (
            <div
              key={`${user.role}-${user.email}`}
              className="space-y-2 rounded-lg border border-outline-variant/40 p-3"
              data-testid={`seeded-user-${key}`}
              data-role={user.role}
            >
              <CopyRow label="Role" value={user.role} />
              <CopyRow
                label="Email"
                value={user.email}
                testId={isAdmin ? "invite-email" : `invite-email-${key}`}
              />
              {url && (
                <CopyRow
                  label="Invite URL"
                  value={url}
                  testId={isAdmin ? "invite-url" : `invite-url-${key}`}
                  mono
                />
              )}
              {isAdmin && invite.token && !url && (
                <CopyRow label="Invite token" value={invite.token} testId="invite-token" mono />
              )}
            </div>
          );
        })}
      </div>
      <p className="text-[12px] leading-[18px] text-on-variant">
        Login page: leave Super Admin tenant ID empty. Tenant users enter this Tenant ID, their email, and the
        password from the invite (or the optional temporary admin password).
      </p>
    </div>
  );
}

function CopyRow({
  label,
  value,
  mono,
  testId,
}: {
  label: string;
  value: string;
  mono?: boolean;
  testId?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-outline-variant/40 bg-surface-lowest px-3 py-2" data-testid={testId}>
      <div className="flex items-center justify-between gap-2">
        <dt className="text-[11px] font-medium uppercase tracking-wide text-on-variant">{label}</dt>
        <button
          className="link-action"
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <dd className={`mt-1 break-all ${mono ? "font-mono text-code-md" : "font-medium"}`}>{value}</dd>
    </div>
  );
}

function formatExpiry(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between gap-4 border-b border-outline-variant/30 py-2 last:border-0">
      <dt className="text-on-variant">{label}</dt>
      <dd className="font-medium">{value || "—"}</dd>
    </div>
  );
}
