import { FormEvent, useEffect, useMemo, useState } from "react";
import { asList, rolesApi } from "../api/client";
import { PERMISSION_GROUPS, hasAnyPermission, permissionGroup, type PermissionGroup } from "../auth/access";
import { useCurrentUser } from "../auth/CurrentUserContext";
import Modal from "../components/Modal";
import { Alert, PageHeader } from "../components/ui";

type RoleRow = {
  id: string;
  name: string;
  description?: string | null;
  permission_codes?: string[];
  permissions?: string[];
  is_system?: boolean;
};

type PermItem = {
  code: string;
  label: string;
  group: PermissionGroup;
};

function normalizePermissions(data: unknown): PermItem[] {
  const rows = asList<unknown>(data);
  return rows
    .map((row) => {
      if (typeof row === "string") {
        return { code: row, label: row, group: permissionGroup(row) };
      }
      if (row && typeof row === "object") {
        const rec = row as { id?: string; code?: string; name?: string; description?: string; group?: string };
        const code = rec.code || rec.id || rec.name || "";
        if (!code) return null;
        return {
          code,
          label: rec.name || rec.description || code,
          group: permissionGroup(code, rec.group),
        };
      }
      return null;
    })
    .filter((item): item is PermItem => Boolean(item));
}

function rolePermissionCodes(role: RoleRow): string[] {
  const perms = role.permission_codes || role.permissions;
  if (!Array.isArray(perms)) return [];
  return perms.map((p) => (typeof p === "string" ? p : String(p))).filter(Boolean);
}

export default function RolesPage() {
  const user = useCurrentUser();
  const canCreate = hasAnyPermission(user, ["roles.create", "user:manage"]);
  const canUpdate = hasAnyPermission(user, ["roles.update", "user:manage"]);
  const canDelete = hasAnyPermission(user, ["roles.delete", "user:manage"]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [catalog, setCatalog] = useState<PermItem[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<RoleRow | "new" | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState(false);

  async function refresh() {
    const [roleData, permData] = await Promise.all([rolesApi.list(), rolesApi.permissions().catch(() => [])]);
    setRoles(asList<RoleRow>(roleData));
    setCatalog(normalizePermissions(permData));
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load roles"));
  }, []);

  const grouped = useMemo(() => {
    const buckets = new Map<PermissionGroup, PermItem[]>();
    for (const group of PERMISSION_GROUPS) buckets.set(group, []);
    for (const item of catalog) {
      buckets.get(item.group)?.push(item);
    }
    if (catalog.length === 0) {
      return [] as Array<[PermissionGroup, PermItem[]]>;
    }
    return PERMISSION_GROUPS.map((group) => [group, buckets.get(group) || []] as [PermissionGroup, PermItem[]]).filter(
      ([, items]) => items.length > 0,
    );
  }, [catalog]);

  function openCreate() {
    setError("");
    setEditing("new");
    setName("");
    setDescription("");
    setSelected([]);
  }

  function openEdit(role: RoleRow) {
    setError("");
    setEditing(role);
    setName(role.name);
    setDescription(role.description || "");
    setSelected(rolePermissionCodes(role));
  }

  function togglePerm(code: string) {
    setSelected((prev) => (prev.includes(code) ? prev.filter((x) => x !== code) : [...prev, code]));
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError("");
    try {
      const body = { name: name.trim(), description: description.trim(), permissions: selected };
      if (editing === "new") {
        await rolesApi.create(body);
      } else if (editing) {
        await rolesApi.update(editing.id, body);
      }
      setEditing(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save role");
    } finally {
      setPending(false);
    }
  }

  async function onDelete(role: RoleRow) {
    if (role.is_system) return;
    if (!window.confirm(`Delete role “${role.name}”?`)) return;
    setError("");
    try {
      await rolesApi.remove(role.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete role");
    }
  }

  return (
    <section className="space-y-5">
      <PageHeader
        title="Roles"
        subtitle="Group permissions for Users, Folders, Documents, AI, and Admin."
        actions={
          canCreate ? (
          <button className="btn btn-primary" type="button" onClick={openCreate}>
            + Create Role
          </button>
          ) : undefined
        }
      />
      {error && <Alert>{error}</Alert>}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="panel">
          <div className="data-head cols-4">
            <span>Name</span>
            <span>Description</span>
            <span>Permissions</span>
            <span>Actions</span>
          </div>
          <ul>
            {roles.map((role) => (
              <li key={role.id} className="data-row cols-4">
                <div>
                  <div className="font-medium">{role.name}</div>
                  {role.is_system && <div className="text-label-sm text-on-variant">System role</div>}
                </div>
                <span className="truncate text-on-variant">{role.description || "—"}</span>
                <span className="chip">{rolePermissionCodes(role).length}</span>
                <div className="flex gap-3">
                  {canUpdate && (
                  <button className="link-action" type="button" onClick={() => openEdit(role)}>
                    Edit
                  </button>
                  )}
                  {canDelete && (
                  <button
                    className="link-action disabled:cursor-not-allowed disabled:opacity-40"
                    type="button"
                    disabled={Boolean(role.is_system)}
                    title={role.is_system ? "System roles cannot be deleted" : "Delete role"}
                    onClick={() => onDelete(role)}
                  >
                    Delete
                  </button>
                  )}
                </div>
              </li>
            ))}
            {roles.length === 0 && <li className="px-4 py-8 text-center text-body-md text-on-variant">No roles yet.</li>}
          </ul>
        </div>
        <aside className="space-y-3">
          {roles.map((role) => (
            <div key={`card-${role.id}`} className="panel p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-headline-sm">{role.name}</div>
                  <p className="mt-1 text-body-sm text-on-variant">{role.description || "Permission bundle"}</p>
                </div>
                {role.is_system && <span className="chip">System</span>}
              </div>
              <p className="mt-3 text-label-sm text-on-variant">{rolePermissionCodes(role).length} permissions</p>
            </div>
          ))}
        </aside>
      </div>

      {editing && (
        <Modal title={editing === "new" ? "Create Role" : "Edit Role"} onClose={() => setEditing(null)} wide>
          <form className="mt-4 space-y-3 text-sm" onSubmit={onSave}>
            <label className="block">
              Name
              <input
                className="input-field mt-1"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <label className="block">
              Description
              <input
                className="input-field mt-1"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            {grouped.length === 0 && (
              <p className="text-on-variant">No permission catalog yet. You can still save the role name.</p>
            )}
            {grouped.map(([group, items]) => (
              <fieldset key={group} className="rounded-lg border border-outline-variant/50 p-3">
                <legend className="px-1 text-[12px] font-semibold uppercase tracking-wide text-on-variant">{group}</legend>
                <div className="grid gap-1 md:grid-cols-2">
                  {items.map((item) => (
                    <label key={item.code} className="flex items-center gap-2 rounded-md px-1 py-1 hover:bg-surface-low">
                      <input type="checkbox" checked={selected.includes(item.code)} onChange={() => togglePerm(item.code)} />
                      <span>
                        {item.label}
                        {item.label !== item.code && (
                          <span className="ml-1 font-mono text-[11px] text-on-variant">{item.code}</span>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
            <div className="flex justify-end gap-2 pt-2">
              <button className="btn btn-secondary" type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" type="submit" disabled={pending}>
                {pending ? "Saving…" : "Save role"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
