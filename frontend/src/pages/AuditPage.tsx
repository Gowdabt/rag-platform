import { useEffect, useState } from "react";
import { adminApi, asList } from "../api/client";
import { AuditTable } from "./PlatformAuditPage";

type AuditRow = {
  id?: string;
  action?: string;
  actor_email?: string;
  actor?: string;
  created_at?: string;
};

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    adminApi
      .audit()
      .then((data) => setRows(asList<AuditRow>(data)))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load audit logs"));
  }, []);

  return (
    <section className="space-y-5">
      <div>
        <h1 className="page-title">Audit</h1>
        <p className="page-sub">Security and admin events for this tenant.</p>
      </div>
      {error && <p className="banner-error">{error}</p>}
      <AuditTable rows={rows} />
    </section>
  );
}
