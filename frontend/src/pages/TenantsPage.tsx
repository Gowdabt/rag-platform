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

export default function TenantsPage() {
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  const [openCreate, setOpenCreate] = useState(false);
  const [view, setView] = useState<TenantRow | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [slug, setSlug] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
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
    setBanner("");
    setPending(true);
    try {
      const created = await platformApi.createTenant({
        company_name: companyName.trim(),
        slug: slug.trim(),
        admin_name: adminName.trim(),
        admin_email: adminEmail.trim(),
      });
      const token = created?.invitation_token || created?.invite_token;
      setBanner(
        token
          ? `Tenant created. Invitation token (dev): ${token}`
          : "Tenant created.",
      );
      setOpenCreate(false);
      setCompanyName("");
      setSlug("");
      setAdminName("");
      setAdminEmail("");
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
        subtitle="Provision companies, suspend access, and copy invite tokens in development."
        actions={
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              setError("");
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
      {error && <Alert>{error}</Alert>}
      {banner && <Alert tone="ok">{banner}</Alert>}
      <div className="panel">
        <div className="table-head grid-cols-[2fr_1fr_1.4fr_auto_auto]">
          <span>Company</span>
          <span>Tenant ID</span>
          <span>Admin email</span>
          <span>Status</span>
          <span>Actions</span>
        </div>
        <ul>
          {tenants.map((t) => {
            const status = (t.status || "active").toLowerCase();
            return (
              <li key={t.id} className="table-row grid-cols-[2fr_1fr_1.4fr_auto_auto]">
                <span className="font-medium">{t.company_name || t.name || "—"}</span>
                <span className="truncate font-mono text-code-md text-on-variant">{t.slug || t.id}</span>
                <span className="truncate text-on-variant">{t.admin_email || "—"}</span>
                <StatusPill status={t.status || "active"} />
                <div className="flex flex-wrap gap-3">
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
            <label className="block">
              Company name
              <input
                className="input-field mt-1"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                required
              />
            </label>
            <label className="block">
              Tenant ID (slug)
              <input
                className="input-field mt-1 font-mono"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="acme"
                required
              />
            </label>
            <label className="block">
              Admin name
              <input
                className="input-field mt-1"
                value={adminName}
                onChange={(e) => setAdminName(e.target.value)}
                required
              />
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

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between gap-4 border-b border-outline-variant/30 py-2 last:border-0">
      <dt className="text-on-variant">{label}</dt>
      <dd className="font-medium">{value || "—"}</dd>
    </div>
  );
}
