import { useEffect, useState } from "react";
import { adminApi, ApiError, asList, platformApi } from "../api/client";

type CatalogModel = {
  id?: string;
  name?: string;
  model?: string;
  provider?: string;
  allowed?: boolean;
};

function catalogModels(data: unknown): CatalogModel[] {
  if (Array.isArray(data) && data.every((item) => typeof item === "string")) {
    return (data as string[]).map((id) => ({ id, name: id, model: id }));
  }
  const rows = asList<CatalogModel | string>(data);
  return rows.map((row) => (typeof row === "string" ? { id: row, name: row, model: row } : row));
}

export default function PlatformConfigPage() {
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [config, setConfig] = useState<unknown>(null);
  const [configNote, setConfigNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    platformApi
      .aiCatalog()
      .then((data) => setModels(catalogModels(data)))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load AI catalog"));
    adminApi
      .config()
      .then((data) => setConfig(data))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setConfigNote("Global config is restricted. Showing the AI catalog only.");
          return;
        }
        setConfigNote(err instanceof Error ? err.message : "Could not load global config");
      });
  }, []);

  return (
    <section className="space-y-5">
      <div>
        <h1 className="page-title">Platform configuration</h1>
        <p className="page-sub">Allowed models for tenant AI configuration. Model must be in the platform allow-list.</p>
      </div>
      {error && <p className="banner-error">{error}</p>}
      {configNote && <p className="text-sm text-on-variant">{configNote}</p>}
      <div className="panel">
        <div className="data-head cols-3">
          <span>Model</span>
          <span>Provider</span>
          <span>Allow-list</span>
        </div>
        <ul>
          {models.map((m, i) => {
            const label = m.name || m.model || m.id || `model-${i}`;
            return (
              <li key={m.id || label} className="data-row cols-3">
                <div>
                  <div className="font-medium">{label}</div>
                  {m.id && m.id !== label && <div className="font-mono text-[11px] text-on-variant">{m.id}</div>}
                </div>
                <span className="text-on-variant">{m.provider || "—"}</span>
                <span className="text-[12px] text-on-variant">{m.allowed === false ? "Blocked" : "Allowed"}</span>
              </li>
            );
          })}
          {models.length === 0 && <li className="px-4 py-8 text-center text-sm text-on-variant">No catalog models returned.</li>}
        </ul>
      </div>
      {config != null && (
        <div className="overflow-hidden rounded-xl border border-outline-variant/50 bg-primary-container p-4 shadow-card">
          <h2 className="text-[13px] font-medium text-surface-highest">Global configuration</h2>
          <pre className="mt-2 overflow-auto font-mono text-[11px] text-surface-high">{JSON.stringify(config, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}
