import { FormEvent, useEffect, useMemo, useState } from "react";
import { asList, foldersApi, rolesApi } from "../api/client";
import Modal from "../components/Modal";
import { Alert, PageHeader } from "../components/ui";
import { untrustedText } from "../security/untrusted";

type Folder = {
  id: string;
  name: string;
  parent_id?: string | null;
  children?: Folder[];
};

type Grant = {
  id: string;
  type?: "user" | "role";
  principal_type?: "user" | "role";
  email?: string;
  role_id?: string;
  role_name?: string;
  permissions?: string[] | Record<string, boolean>;
};

type RoleOption = { id: string; name: string };

type AccessFlags = {
  view: boolean;
  edit: boolean;
  upload: boolean;
  delete: boolean;
  share: boolean;
};

const EMPTY_ACCESS: AccessFlags = { view: true, edit: false, upload: false, delete: false, share: false };

function flattenFolders(rows: Folder[], parentId: string | null = null, seen = new Set<string>()): Folder[] {
  const out: Folder[] = [];
  for (const row of rows) {
    if (!row?.id || seen.has(row.id)) continue;
    seen.add(row.id);
    const node: Folder = {
      id: row.id,
      name: row.name,
      parent_id: row.parent_id ?? parentId,
      children: row.children,
    };
    out.push(node);
    if (row.children?.length) out.push(...flattenFolders(row.children, row.id, seen));
  }
  return out;
}

function grantType(grant: Grant): "user" | "role" {
  return grant.type || grant.principal_type || (grant.role_id || grant.role_name ? "role" : "user");
}

function grantPerms(grant: Grant): string {
  const p = grant.permissions;
  if (Array.isArray(p)) return p.join(", ") || "—";
  if (p && typeof p === "object") {
    return Object.entries(p)
      .filter(([, v]) => Boolean(v))
      .map(([k]) => k)
      .join(", ") || "—";
  }
  return "—";
}

export default function FoldersPage() {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [shareType, setShareType] = useState<"user" | "role">("user");
  const [shareEmail, setShareEmail] = useState("");
  const [shareRole, setShareRole] = useState("");
  const [access, setAccess] = useState<AccessFlags>(EMPTY_ACCESS);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const flat = useMemo(() => flattenFolders(folders), [folders]);
  const byParent = useMemo(() => {
    const map = new Map<string | null, Folder[]>();
    for (const folder of flat) {
      const key = folder.parent_id || null;
      const list = map.get(key) || [];
      list.push(folder);
      map.set(key, list);
    }
    return map;
  }, [flat]);
  const selected = flat.find((f) => f.id === selectedId) || null;

  async function refresh() {
    const [folderData, roleData] = await Promise.all([foldersApi.list(), rolesApi.list().catch(() => [])]);
    const rows = asList<Folder>(folderData);
    setFolders(rows);
    setRoles(asList<RoleOption>(roleData).map((r) => ({ id: r.id, name: r.name || r.id })));
    if (rows.length && !selectedId) {
      const first = flattenFolders(rows)[0];
      if (first) setSelectedId(first.id);
    }
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load folders"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setGrants([]);
      return;
    }
    foldersApi
      .shares(selectedId)
      .then((data) => setGrants(asList<Grant>(data)))
      .catch(() => setGrants([]));
  }, [selectedId]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError("");
    try {
      const created = await foldersApi.create({ name: name.trim(), parent_id: selectedId });
      setName("");
      await refresh();
      if (created?.id) setSelectedId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create folder");
    }
  }

  async function onRename(e: FormEvent) {
    e.preventDefault();
    if (!selectedId || !renameValue.trim()) return;
    try {
      await foldersApi.update(selectedId, { name: renameValue.trim() });
      setRenameOpen(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not rename folder");
    }
  }

  async function onDelete() {
    if (!selectedId) return;
    if (!window.confirm("Delete this folder?")) return;
    setError("");
    try {
      await foldersApi.remove(selectedId);
      setSelectedId(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete folder");
    }
  }

  async function onShare(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    setError("");
    try {
      await foldersApi.share(selectedId, {
        type: shareType,
        email: shareType === "user" ? shareEmail.trim() : undefined,
        role_id: shareType === "role" ? shareRole : undefined,
        permissions: access,
      });
      setShareEmail("");
      const data = await foldersApi.shares(selectedId);
      setGrants(asList<Grant>(data));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not share folder");
    }
  }

  async function onUnshare(grantId: string) {
    if (!selectedId) return;
    try {
      await foldersApi.unshare(selectedId, grantId);
      setGrants((prev) => prev.filter((g) => g.id !== grantId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove access");
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function renderTree(parentId: string | null, depth: number) {
    const nodes = byParent.get(parentId) || [];
    return nodes.map((folder) => {
      const kids = byParent.get(folder.id) || [];
      const open = expanded.has(folder.id) || depth === 0;
      return (
        <li key={folder.id}>
          <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
            {kids.length > 0 ? (
              <button className="w-5 text-[11px] text-on-variant" type="button" onClick={() => toggleExpand(folder.id)}>
                {open ? "▾" : "▸"}
              </button>
            ) : (
              <span className="w-5" />
            )}
            <button
              type="button"
              className={`min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-[13px] ${
                folder.id === selectedId ? "bg-surface-lowest font-medium shadow-sm" : "text-on-variant hover:bg-surface-lowest/70"
              }`}
              onClick={() => setSelectedId(folder.id)}
            >
              {untrustedText(folder.name)}
            </button>
          </div>
          {open && kids.length > 0 && <ul>{renderTree(folder.id, depth + 1)}</ul>}
        </li>
      );
    });
  }

  return (
    <section className="space-y-5">
      <PageHeader
        title="Data"
        subtitle="Folders for this tenant. Share view, edit, upload, delete, and share access with users or roles."
      />
      {error && <Alert>{error}</Alert>}
      <div className="flex min-h-[calc(100vh-12rem)] overflow-hidden rounded-xl bg-surface-lowest shadow-card">
        <aside className="flex w-72 shrink-0 flex-col bg-surface-low/70">
          <div className="flex items-center justify-between px-3 pt-3">
            <span className="page-kicker">Folders</span>
          </div>
          <form className="flex gap-2 p-3" onSubmit={onCreate}>
            <input
              className="input-field min-w-0 flex-1"
              placeholder={selected ? `Folder in ${selected.name}` : "New folder"}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button className="btn btn-primary" type="submit">
              Create
            </button>
          </form>
          {selected && (
            <button
              className="px-3 pb-2 text-left text-label-sm text-on-variant underline underline-offset-2"
              type="button"
              onClick={() => setSelectedId(null)}
            >
              Create at root instead
            </button>
          )}
          <ul className="flex-1 overflow-y-auto px-2 pb-3">{renderTree(null, 0)}</ul>
          {flat.length === 0 && <p className="px-4 pb-4 text-body-sm text-on-variant">No folders yet. Create one to get started.</p>}
        </aside>
        <div className="min-w-0 flex-1 bg-surface-low/30 p-5">
          {!selected && <p className="text-body-md text-on-variant">Select a folder to rename, delete, or share it.</p>}
          {selected && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-headline-sm">{untrustedText(selected.name)}</h2>
                  <p className="text-body-sm text-on-variant">Share panel for this folder</p>
                </div>
                <div className="flex gap-2">
                  <button
                    className="btn btn-secondary"
                    type="button"
                    onClick={() => {
                      setRenameValue(selected.name);
                      setRenameOpen(true);
                    }}
                  >
                    Rename
                  </button>
                  <button className="btn btn-danger" type="button" onClick={onDelete}>
                    Delete
                  </button>
                </div>
              </div>
              <div className="panel p-4">
                <h3 className="text-headline-sm">Access</h3>
                <ul className="mt-3 space-y-2 text-body-md">
                  {grants.map((grant) => (
                    <li key={grant.id} className="flex items-center justify-between rounded-lg bg-surface-low px-3 py-2">
                      <div>
                        <span className="font-medium">
                          {grantType(grant) === "role" ? grant.role_name || grant.role_id : grant.email}
                        </span>
                        <span className="ml-2 text-label-sm uppercase tracking-wide text-on-variant">{grantType(grant)}</span>
                        <div className="text-body-sm text-on-variant">{grantPerms(grant)}</div>
                      </div>
                      <button className="link-action" type="button" onClick={() => onUnshare(grant.id)}>
                        Remove
                      </button>
                    </li>
                  ))}
                  {grants.length === 0 && <li className="text-on-variant">No grants yet.</li>}
                </ul>
                <form className="mt-4 space-y-3 border-t border-outline-variant/40 pt-4 text-body-md" onSubmit={onShare}>
                  <h4 className="font-medium">Add Access</h4>
                  <label className="block">
                    Type
                    <select
                      className="ml-2 rounded-lg border border-outline-variant px-2 py-1"
                      value={shareType}
                      onChange={(e) => setShareType(e.target.value as "user" | "role")}
                    >
                      <option value="user">User</option>
                      <option value="role">Role</option>
                    </select>
                  </label>
                  {shareType === "user" ? (
                    <label className="block">
                      Email
                      <input
                        className="input-field mt-1"
                        type="email"
                        value={shareEmail}
                        onChange={(e) => setShareEmail(e.target.value)}
                        required
                      />
                    </label>
                  ) : (
                    <label className="block">
                      Role
                      <select
                        className="input-field mt-1"
                        value={shareRole}
                        onChange={(e) => setShareRole(e.target.value)}
                        required
                      >
                        <option value="">Select a role</option>
                        {roles.map((role) => (
                          <option key={role.id} value={role.id}>
                            {untrustedText(role.name)}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <div className="flex flex-wrap gap-3">
                    {(["view", "edit", "upload", "delete", "share"] as const).map((key) => (
                      <label key={key} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={access[key]}
                          onChange={(e) => setAccess((prev) => ({ ...prev, [key]: e.target.checked }))}
                        />
                        {key}
                      </label>
                    ))}
                  </div>
                  <button className="btn btn-primary" type="submit">
                    Add access
                  </button>
                </form>
              </div>
            </div>
          )}
        </div>
      </div>
      {renameOpen && selected && (
        <Modal title="Rename folder" onClose={() => setRenameOpen(false)}>
          <form className="mt-4 space-y-3 text-sm" onSubmit={onRename}>
            <input
              className="input-field"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button className="btn btn-secondary" type="button" onClick={() => setRenameOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" type="submit">
                Save
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
