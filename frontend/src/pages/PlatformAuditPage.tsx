import { useEffect, useState } from "react";
import { adminApi, asList, platformApi } from "../api/client";
import { formatWhen } from "../auth/access";

type AuditRow = {
  id?: string;
  action?: string;
  actor_email?: string;
  actor?: string;
  tenant_slug?: string;
  created_at?: string;
};

export default function PlatformAuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    platformApi
      .auditLogs()
      .then((data) => setRows(asList<AuditRow>(data)))
      .catch(() =>
        adminApi
          .audit()
          .then((data) => setRows(asList<AuditRow>(data)))
          .catch((err) => setError(err instanceof Error ? err.message : "Could not load audit logs")),
      );
  }, []);

  return (
    <section className="space-y-5">
      <div>
        <h1 className="page-title">Audit logs</h1>
        <p className="page-sub">Platform-wide events across tenants.</p>
      </div>
      {error && <p className="banner-error">{error}</p>}
      <AuditTable rows={rows} showTenant />
    </section>
  );
}

export function AuditTable({ rows, showTenant }: { rows: AuditRow[]; showTenant?: boolean }) {
  return (
    <div className="panel">
      <div
        className={`grid gap-3 border-b border-outline-variant/40 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-on-variant ${
          showTenant ? "grid-cols-[1.4fr_1fr_1fr_auto]" : "grid-cols-[1.6fr_1fr_auto]"
        }`}
      >
        <span>Action</span>
        <span>Actor</span>
        {showTenant && <span>Tenant</span>}
        <span>When</span>
      </div>
      <ul>
        {rows.map((row, i) => (
          <li
            key={row.id || `${row.action}-${i}`}
            className={`grid gap-3 border-b border-outline-variant/30 px-4 py-3 text-[13px] last:border-0 ${
              showTenant ? "grid-cols-[1.4fr_1fr_1fr_auto]" : "grid-cols-[1.6fr_1fr_auto]"
            }`}
          >
            <span className="font-medium">{row.action || "—"}</span>
            <span className="truncate text-on-variant">{row.actor_email || row.actor || "—"}</span>
            {showTenant && <span className="font-mono text-[12px] text-on-variant">{row.tenant_slug || "—"}</span>}
            <span className="text-[12px] text-on-variant">{formatWhen(row.created_at)}</span>
          </li>
        ))}
        {rows.length === 0 && <li className="px-4 py-8 text-center text-sm text-on-variant">No audit events yet.</li>}
      </ul>
    </div>
  );
}
