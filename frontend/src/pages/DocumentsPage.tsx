import { useEffect, useState } from "react";
import { docs } from "../api/client";
import { untrustedText } from "../security/untrusted";

type Doc = {
  id: string;
  title: string;
  path: string;
  status?: string;
  version_number?: number;
  size_bytes?: number | null;
  mime_type?: string | null;
  storage_key?: string | null;
  storage_provider?: string;
  storage_root?: string;
};

type Version = {
  id: string;
  version_number: number;
  status: string;
  content_hash: string;
  created_at?: string | null;
};

export default function DocumentsPage() {
  const [items, setItems] = useState<Doc[]>([]);
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, Version[]>>({});
  const [query, setQuery] = useState("");

  async function refresh() {
    setItems(await docs.list());
  }

  useEffect(() => {
    refresh().catch((e) => setStatus(String(e)));
  }, []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setStatus("Uploading…");
    const result = await docs.upload(file);
    setStatus(
      result.status === "completed"
        ? `Indexed as “${untrustedText(file.name)}” in this workspace.`
        : result.status === "unchanged"
          ? "Same content — kept the existing version."
          : `Upload ${result.status}`,
    );
    await refresh();
  }

  async function toggleVersions(id: string) {
    if (openId === id) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    if (!versions[id]) {
      const rows = await docs.versions(id);
      setVersions((prev) => ({ ...prev, [id]: rows }));
    }
  }

  const storageHint = items[0];
  const ready = items.filter((d) => d.status === "ready" || d.status === "completed").length;
  const failed = items.filter((d) => (d.status || "").includes("fail")).length;
  const bytes = items.reduce((sum, d) => sum + (d.size_bytes || 0), 0);
  const visible = items.filter((d) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return d.title.toLowerCase().includes(q) || d.path.toLowerCase().includes(q);
  });

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Documents</h1>
          <p className="page-sub">
            {items.length} {items.length === 1 ? "item" : "items"} · re-uploading the same filename creates a new version
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="input-field w-56"
            placeholder="Search documents…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <label className="btn btn-primary cursor-pointer">
            Upload document
            <input
              className="sr-only"
              type="file"
              onChange={(e) => {
                onFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Indexed" value={String(items.length)} />
        <Stat label="Ready" value={String(ready)} />
        <Stat label="Storage" value={formatBytes(bytes)} />
        <Stat label="Failed" value={String(failed)} warn={failed > 0} />
      </div>

      {status && <p className="text-sm text-on-surface">{status}</p>}

      <div className="panel">
        <div className="table-head grid-cols-[2fr_1fr_auto_auto_auto]">
          <span>Document</span>
          <span>Path</span>
          <span>Version</span>
          <span>Status</span>
          <span>Size</span>
        </div>
        <ul>
          {visible.map((d) => (
            <li key={d.id} className="border-b border-outline-variant/30 px-4 py-3 last:border-0 hover:bg-background">
              <div className="grid grid-cols-[2fr_1fr_auto_auto_auto] items-center gap-3 text-[13px]">
                <div>
                  <div className="font-medium">{untrustedText(d.title)}</div>
                  <button
                    className="mt-0.5 text-[11px] text-secondary underline"
                    type="button"
                    onClick={() => toggleVersions(d.id)}
                  >
                    {openId === d.id ? "Hide versions" : "Versions"}
                  </button>
                </div>
                <div className="truncate font-mono text-[11px] text-on-variant">{untrustedText(d.path)}</div>
                <span className="font-mono text-[12px]">v{d.version_number ?? 1}</span>
                <Status status={d.status || "pending"} />
                <span className="text-[12px] text-on-variant">
                  {d.size_bytes != null ? formatBytes(d.size_bytes) : "—"}
                </span>
              </div>
              {openId === d.id && (
                <ul className="mt-2 space-y-1 rounded-lg bg-surface-low px-3 py-2 text-[12px] text-on-variant">
                  {(versions[d.id] || []).map((v) => (
                    <li key={v.id}>
                      v{v.version_number} · {v.status}
                      {v.created_at ? ` · ${new Date(v.created_at).toLocaleString()}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {visible.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-on-variant">Nothing indexed yet.</li>
          )}
        </ul>
      </div>

      <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-outline-variant bg-surface-low/50 px-6 py-10 text-sm text-on-variant hover:border-secondary">
        <span className="font-medium text-on-surface">Drag and drop files here, or click to browse</span>
        <span className="mt-1 text-[12px]">
          Originals stay under{" "}
          <code className="rounded bg-surface-lowest px-1 font-mono text-[11px]">
            {storageHint?.storage_root || "data/objects"}
          </code>
        </span>
        <input
          className="sr-only"
          type="file"
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </label>
    </section>
  );
}

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${warn ? "text-error" : ""}`}>{value}</div>
    </div>
  );
}

function Status({ status }: { status: string }) {
  const ok = status === "ready" || status === "completed";
  const bad = status.includes("fail");
  const cls = ok
    ? "bg-emerald-50 text-success"
    : bad
      ? "bg-error-container text-on-error-container"
      : "bg-surface-container text-on-variant";
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>{status}</span>;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
