import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { asList, docs } from "../api/client";
import { hasAnyPermission, roleNames } from "../auth/access";
import { useCurrentUser } from "../auth/CurrentUserContext";
import type { AppUser } from "../auth/types";
import { untrustedText } from "../security/untrusted";

type DocAcl = {
  visibility?: string;
  allowed_roles?: string[];
  owner_id?: string;
};

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
  owner_user_id?: string | null;
  acl?: DocAcl;
};

type Version = {
  id: string;
  version_number: number;
  status: string;
  content_hash: string;
  created_at?: string | null;
};

/** Presets map to seeded roles only: Member, Viewer, Tenant Admin (+ tenant-wide). */
const VISIBILITY_PRESETS = [
  { id: "only_me", label: "Only me", visibility: "private" as const, allowedRoles: [] as string[] },
  { id: "members", label: "Members", visibility: "private" as const, allowedRoles: ["Member"] },
  { id: "viewers", label: "Viewers", visibility: "private" as const, allowedRoles: ["Viewer"] },
  {
    id: "tenant_admins",
    label: "Tenant Admins",
    visibility: "private" as const,
    allowedRoles: ["Tenant Admin"],
  },
  {
    id: "members_viewers",
    label: "Members and Viewers",
    visibility: "private" as const,
    allowedRoles: ["Member", "Viewer"],
  },
  {
    id: "tenant",
    label: "Everyone in this tenant",
    visibility: "tenant" as const,
    allowedRoles: [] as string[],
  },
];

function defaultPresetId(roles: string[]): string {
  if (roles.some((r) => r === "Tenant Admin" || r === "Admin")) return "tenant";
  return "only_me";
}

function describeAcl(acl: DocAcl | undefined): string {
  if (!acl) return "—";
  if (acl.visibility === "tenant") return "Everyone in tenant";
  const roles = acl.allowed_roles || [];
  if (roles.length === 0) return "Only me";
  return roles.join(", ");
}

/** Read/search access is not ownership. Only the uploader or a Tenant Admin may retarget visibility. */
function accessSentence(doc: Doc): string {
  const who = describeAcl(doc.acl);
  if (doc.acl?.visibility === "tenant") {
    return "Everyone in this tenant can read this file. A question can cite it.";
  }
  return `Visible to ${who.toLowerCase()}. People outside that audience will not see it in search or chat.`;
}

function questionFor(title: string): string {
  const name = title.replace(/\.[^.]+$/, "");
  return `What does ${name} say?`;
}

function canEditDocumentVisibility(user: AppUser | null, doc: Doc): boolean {
  if (!user?.user_id) return false;
  if (roleNames(user).some((role) => role === "Tenant Admin" || role === "Admin")) return true;
  if (doc.owner_user_id && doc.owner_user_id === user.user_id) return true;
  return Boolean(doc.acl?.owner_id && doc.acl.owner_id === user.user_id);
}

export default function DocumentsPage() {
  const user = useCurrentUser();
  const canUpload = hasAnyPermission(user, ["document:write", "documents.upload"]);
  const roles = roleNames(user);
  const [items, setItems] = useState<Doc[]>([]);
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, Version[]>>({});
  const [query, setQuery] = useState("");
  const [visibilityPreset, setVisibilityPreset] = useState(() => defaultPresetId(roles));
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchParams] = useSearchParams();

  useEffect(() => {
    setVisibilityPreset(defaultPresetId(roles));
  }, [roles.join("|")]);

  const selectedPreset = useMemo(
    () => VISIBILITY_PRESETS.find((p) => p.id === visibilityPreset) || VISIBILITY_PRESETS[0],
    [visibilityPreset],
  );

  async function refresh() {
    setItems(asList<Doc>(await docs.list()));
  }

  useEffect(() => {
    refresh()
      .catch((e) => setStatus(e instanceof Error ? e.message : "Could not load documents."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const focus = searchParams.get("focus");
    if (focus) setSelectedId(focus);
  }, [searchParams]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setStatus("Uploading and indexing…");
    try {
      const result = await docs.upload(file, {
        visibility: selectedPreset.visibility,
        allowedRoles: selectedPreset.allowedRoles,
      });
      setStatus(
        result.status === "completed"
          ? `Indexed as “${untrustedText(file.name)}” · visible to ${selectedPreset.label.toLowerCase()}.`
          : result.status === "unchanged"
            ? "Same content — kept the existing version."
            : result.error
              ? `Upload ${result.status}. ${result.error}`
              : `Upload finished with status ${result.status}.`,
      );
      await refresh();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Upload failed. Check the file and try again.");
    }
  }

  async function onChangeVisibility(doc: Doc, presetId: string) {
    const preset = VISIBILITY_PRESETS.find((p) => p.id === presetId);
    if (!preset) return;
    setStatus("Updating visibility…");
    try {
      await docs.share(doc.id, {
        visibility: preset.visibility,
        allowed_roles: preset.allowedRoles,
      });
      setStatus(`Visibility for “${untrustedText(doc.title)}” set to ${preset.label.toLowerCase()}.`);
      await refresh();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Could not update visibility. Try again.");
    }
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
  const selected = items.find((d) => d.id === selectedId) || null;

  return (
    <section className="space-y-5">
      <div>
        <h1 className="page-title">Documents</h1>
        <p className="page-sub max-w-3xl">
          {loading
            ? "Loading documents…"
            : `${items.length} ${items.length === 1 ? "file you can read" : "files you can read"}.`}{" "}
          Visibility is applied before search and chat. Re-uploading the same filename creates a new version.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <input
          className="input-field w-full min-w-[14rem] max-w-xs shrink-0 sm:w-64"
          placeholder="Search documents…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search documents"
        />
        {canUpload && (
          <>
            <label className="flex w-full min-w-[14rem] max-w-xs shrink-0 flex-col gap-1 text-[11px] font-medium leading-4 text-on-variant sm:w-60">
              <span>Visible to</span>
              <select
                className="input-field w-full"
                data-testid="upload-visibility"
                value={visibilityPreset}
                onChange={(e) => setVisibilityPreset(e.target.value)}
              >
                {VISIBILITY_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="btn btn-primary h-9 shrink-0 cursor-pointer">
              Upload document
              <input
                className="sr-only"
                type="file"
                data-testid="upload-file"
                onChange={(e) => {
                  onFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
          </>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Indexed" value={String(items.length)} />
        <Stat label="Ready" value={String(ready)} />
        <Stat label="Storage" value={formatBytes(bytes)} />
        <Stat label="Failed" value={String(failed)} warn={failed > 0} />
      </div>

      {status && (
        <p className={/fail|could not|error/i.test(status) ? "banner-error" : "banner-ok"}>{status}</p>
      )}

      {selected && (
        <article className="rounded-xl border border-outline-variant/50 bg-surface-lowest p-4 shadow-card">
          <p className="text-label-sm font-medium uppercase tracking-[0.02em] text-on-variant">Document</p>
          <h2 className="mt-1 text-headline-sm">{untrustedText(selected.title)}</h2>
          <p className="mt-1 text-body-sm text-on-variant">
            Visible to {describeAcl(selected.acl).toLowerCase()} · {selected.status || "pending"} · v
            {selected.version_number ?? 1}
          </p>
          <p className="mt-2 max-w-3xl text-body-md">{accessSentence(selected)}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              className="btn btn-primary"
              to={`/?fresh=1&q=${encodeURIComponent(questionFor(selected.title))}`}
            >
              Ask about this file
            </Link>
            <button className="btn btn-secondary" type="button" onClick={() => toggleVersions(selected.id)}>
              {openId === selected.id ? "Hide versions" : "Show versions"}
            </button>
          </div>
          {openId === selected.id && (
            <ul className="mt-3 space-y-1 text-body-sm text-on-variant">
              {(versions[selected.id] || []).map((v) => (
                <li key={v.id}>
                  v{v.version_number} · {v.status}
                  {v.created_at ? ` · ${new Date(v.created_at).toLocaleString()}` : ""}
                </li>
              ))}
              {versions[selected.id]?.length === 0 && <li>No versions returned.</li>}
            </ul>
          )}
        </article>
      )}

      <div className="panel">
        <div className="data-head cols-6">
          <span>Document</span>
          <span>Path</span>
          <span>Version</span>
          <span>Status</span>
          <span>Visibility</span>
          <span>Size</span>
        </div>
        <ul>
          {visible.map((d) => (
            <li key={d.id}>
              <div className="data-row cols-6">
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
                <div>
                  {canEditDocumentVisibility(user, d) ? (
                    <select
                      className="input-field w-full max-w-[11rem] text-[11px]"
                      data-testid={`doc-visibility-${d.id}`}
                      value={presetIdForAcl(d.acl)}
                      onChange={(e) => onChangeVisibility(d, e.target.value)}
                    >
                      {VISIBILITY_PRESETS.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-[12px] text-on-variant" data-testid={`doc-visibility-${d.id}`}>
                      {describeAcl(d.acl)}
                    </span>
                  )}
                </div>
                <span className="text-[12px] text-on-variant">
                  {d.size_bytes != null ? formatBytes(d.size_bytes) : "—"}
                </span>
              </div>
              {openId === d.id && (
                <ul className="space-y-1 bg-surface-low px-4 py-2 text-[12px] text-on-variant">
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

      {canUpload && (
      <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-outline-variant bg-surface-low/50 px-6 py-10 text-sm text-on-variant hover:border-secondary">
        <span className="font-medium text-on-surface">Drag and drop files here, or click to browse</span>
        <span className="mt-1 text-[12px]">
          Visible to {selectedPreset.label.toLowerCase()} · originals stay under{" "}
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
      )}
    </section>
  );
}

function presetIdForAcl(acl: DocAcl | undefined): string {
  if (!acl) return "only_me";
  if (acl.visibility === "tenant") return "tenant";
  const roles = [...(acl.allowed_roles || [])].sort().join(",");
  const match = VISIBILITY_PRESETS.find(
    (p) => p.visibility === "private" && [...p.allowedRoles].sort().join(",") === roles,
  );
  return match?.id || "only_me";
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
