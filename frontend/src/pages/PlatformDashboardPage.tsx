import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { asList, platformApi } from "../api/client";
import StatusPill from "../components/StatusPill";
import { Alert, Metric, PageHeader } from "../components/ui";

type TenantRow = {
  id: string;
  name?: string;
  company_name?: string;
  slug?: string;
  status?: string;
  admin_email?: string;
};

export default function PlatformDashboardPage() {
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    platformApi
      .tenants()
      .then((data) => setTenants(asList<TenantRow>(data)))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load tenants"));
  }, []);

  const active = tenants.filter((t) => (t.status || "active").toLowerCase() === "active").length;
  const suspended = tenants.filter((t) => (t.status || "").toLowerCase() === "suspended").length;

  return (
    <section className="space-y-5">
      <PageHeader title="Platform dashboard" subtitle="Tenants, status, and shortcuts for Super Admin." />
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Metric label="Tenants" value={String(tenants.length)} />
        <Metric label="Active" value={String(active)} />
        <Metric label="Suspended" value={String(suspended)} />
      </div>
      <div className="flex gap-2">
        <Link className="btn btn-primary" to="/platform/tenants">
          Manage tenants
        </Link>
        <Link className="btn btn-secondary" to="/platform/config">
          Platform configuration
        </Link>
      </div>
      <div className="panel">
        <div className="data-head cols-3">
          <span>Company</span>
          <span>Tenant ID</span>
          <span>Status</span>
        </div>
        <ul>
          {tenants.slice(0, 8).map((t) => (
            <li key={t.id} className="data-row cols-3" data-testid="tenant-row">
              <span className="min-w-0 truncate font-medium">{t.company_name || t.name || "—"}</span>
              <span className="min-w-0 truncate font-mono text-code-md text-on-variant">{t.slug || t.id}</span>
                <span>
                  <StatusPill status={t.status || "active"} />
                </span>
            </li>
          ))}
          {tenants.length === 0 && <li className="px-4 py-8 text-center text-body-md text-on-variant">No tenants yet.</li>}
        </ul>
      </div>
    </section>
  );
}
