import { FormEvent, useEffect, useState } from "react";
import { asList, invitationsApi, rolesApi, usersApi } from "../api/client";
import { displayRoleList, formatWhen, hasAnyPermission } from "../auth/access";
import { useCurrentUser } from "../auth/CurrentUserContext";
import Modal from "../components/Modal";
import StatusPill from "../components/StatusPill";
import { Alert, PageHeader } from "../components/ui";

type RoleOption = { id: string; name: string };

type UserRow = {
  id: string;
  name?: string | null;
  email?: string;
  roles?: unknown;
  status?: string;
  last_login_at?: string | null;
};

function inviteUrlFrom(result: { invite_path?: string; invitation_token?: string; token?: string } | null): string {
  const path =
    result?.invite_path ||
    (result?.invitation_token ? `/invite?token=${result.invitation_token}` : "") ||
    (result?.token ? `/invite?token=${result.token}` : "");
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${window.location.origin}${path}`;
}

function roleNamesOf(roles: unknown): string[] {
  if (!roles) return [];
  if (Array.isArray(roles)) {
    return roles
      .map((role) => {
        if (typeof role === "string") return role;
        if (role && typeof role === "object") {
          const rec = role as { name?: string; slug?: string };
          return rec.name || rec.slug || "";
        }
        return "";
      })
      .filter(Boolean);
  }
  if (typeof roles === "string") return [roles];
  return [];
}

export default function UsersPage() {
  const me = useCurrentUser();
  const canInvite = hasAnyPermission(me, ["users.create", "user:manage"]);
  const canEdit = hasAnyPermission(me, ["users.update", "user:manage"]);
  const canDisable = hasAnyPermission(me, ["users.disable", "users.update", "user:manage"]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  const [openInvite, setOpenInvite] = useState(false);
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editName, setEditName] = useState("");
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [copyingId, setCopyingId] = useState<string | null>(null);

  async function refresh() {
    const [userData, roleData] = await Promise.all([usersApi.list(), rolesApi.list().catch(() => [])]);
    setUsers(asList<UserRow>(userData));
    setRoles(
      asList<RoleOption>(roleData)
        .map((role) => ({
          id: role.id || role.name,
          name: role.name || role.id,
        }))
        .filter((role) => role.id),
    );
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load users"));
  }, []);

  async function onInvite(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBanner("");
    setPending(true);
    try {
      const roleNames = roles.filter((r) => selected.includes(r.id)).map((r) => r.name);
      await invitationsApi.create({
        name: name.trim(),
        email: email.trim(),
        role_ids: selected,
        role_names: roleNames,
      });
      setBanner("Invitation sent. Use Copy invite on the row until they accept.");
      setOpenInvite(false);
      setName("");
      setEmail("");
      setSelected([]);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send invitation");
    } finally {
      setPending(false);
    }
  }

  function openEdit(user: UserRow) {
    setError("");
    setEditing(user);
    setEditName(user.name || "");
    const names = new Set(roleNamesOf(user.roles));
    setEditRoles(roles.filter((role) => names.has(role.name)).map((role) => role.id));
  }

  async function onSaveEdit(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setError("");
    setBanner("");
    setPending(true);
    try {
      await usersApi.patch(editing.id, { name: editName.trim(), role_ids: editRoles });
      setBanner("User updated.");
      setEditing(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update user");
    } finally {
      setPending(false);
    }
  }

  async function toggleStatus(user: UserRow) {
    const current = (user.status || "active").toLowerCase();
    const next = current === "disabled" || current === "inactive" ? "active" : "disabled";
    setError("");
    try {
      await usersApi.patch(user.id, { status: next });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update user");
    }
  }

  async function copyInvite(user: UserRow) {
    setError("");
    setBanner("");
    setCopyingId(user.id);
    try {
      const result = await usersApi.resendInvite(user.id);
      const url = inviteUrlFrom(result);
      if (!url) {
        setError("Could not create an invite link.");
        return;
      }
      try {
        await navigator.clipboard.writeText(url);
        setBanner("Invite link copied. The previous unused invite no longer works.");
      } catch {
        setBanner(`Invite link: ${url}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not copy invite");
    } finally {
      setCopyingId(null);
    }
  }

  function toggleRole(id: string, into: "invite" | "edit") {
    const set = into === "invite" ? setSelected : setEditRoles;
    set((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <section className="space-y-5">
      <PageHeader
        title="Users"
        subtitle="Invite people to this tenant and disable accounts that should no longer sign in."
        actions={
          canInvite ? (
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => {
                setError("");
                setOpenInvite(true);
              }}
            >
              Invite user
            </button>
          ) : undefined
        }
      />
      {error && <Alert>{error}</Alert>}
      {banner && <Alert tone="ok">{banner}</Alert>}
      <div className="panel">
        <div className="data-head cols-6">
          <span>Name</span>
          <span>Email</span>
          <span>Roles</span>
          <span>Status</span>
          <span>Last login</span>
          <span>Actions</span>
        </div>
        <ul>
          {users.map((user) => {
            const status = (user.status || "active").toLowerCase();
            const disabled = status === "disabled" || status === "inactive";
            const invited = status === "invited";
            return (
              <li key={user.id} className="data-row cols-6" data-testid="user-row">
                <span className="min-w-0 truncate font-medium">{user.name || "—"}</span>
                <span className="min-w-0 truncate">{user.email}</span>
                <span className="min-w-0 truncate text-on-variant">{displayRoleList(user.roles)}</span>
                <span data-testid="user-status">
                  <StatusPill status={user.status || "active"} />
                </span>
                <span className="whitespace-nowrap font-mono text-code-sm text-on-variant" data-testid="user-last-login">
                  {formatWhen(user.last_login_at)}
                </span>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="user-actions">
                  {canEdit && (
                    <button className="link-action" type="button" onClick={() => openEdit(user)}>
                      Edit
                    </button>
                  )}
                  {canInvite && invited && (
                    <button
                      className="link-action"
                      type="button"
                      data-testid="user-copy-invite"
                      disabled={copyingId === user.id}
                      onClick={() => copyInvite(user)}
                    >
                      {copyingId === user.id ? "Copying…" : "Copy invite"}
                    </button>
                  )}
                  {canDisable && (
                    <button className="link-action" type="button" onClick={() => toggleStatus(user)}>
                      {disabled ? "Enable" : "Disable"}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
          {users.length === 0 && <li className="px-4 py-8 text-center text-body-md text-on-variant">No users yet.</li>}
        </ul>
      </div>

      {openInvite && (
        <Modal title="Invite User" onClose={() => setOpenInvite(false)}>
          <form className="mt-4 space-y-3 text-sm" onSubmit={onInvite}>
            {error && <Alert>{error}</Alert>}
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
              Email
              <input
                className="input-field mt-1"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
            <fieldset>
              <legend className="text-sm">Roles</legend>
              <div className="mt-2 max-h-48 space-y-1 overflow-auto rounded-lg border border-outline-variant/50 p-2">
                {roles.map((role) => (
                  <label key={role.id} className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-surface-low">
                    <input type="checkbox" checked={selected.includes(role.id)} onChange={() => toggleRole(role.id, "invite")} />
                    {role.name}
                  </label>
                ))}
                {roles.length === 0 && <p className="px-2 py-1 text-on-variant">No roles returned.</p>}
              </div>
            </fieldset>
            <div className="flex justify-end gap-2 pt-2">
              <button className="btn btn-secondary" type="button" onClick={() => setOpenInvite(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" type="submit" disabled={pending}>
                {pending ? "Sending…" : "Send invitation"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title="Edit user" onClose={() => setEditing(null)}>
          <form className="mt-4 space-y-3 text-sm" onSubmit={onSaveEdit}>
            {error && <Alert>{error}</Alert>}
            <label className="block">
              Name
              <input
                className="input-field mt-1"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                required
              />
            </label>
            <label className="block">
              Email
              <input className="input-field mt-1" value={editing.email || ""} disabled />
              <span className="field-help">Email cannot be changed.</span>
            </label>
            <fieldset>
              <legend className="text-sm">Roles</legend>
              <div className="mt-2 max-h-48 space-y-1 overflow-auto rounded-lg border border-outline-variant/50 p-2">
                {roles.map((role) => (
                  <label key={role.id} className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-surface-low">
                    <input
                      type="checkbox"
                      checked={editRoles.includes(role.id)}
                      onChange={() => toggleRole(role.id, "edit")}
                    />
                    {role.name}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex justify-end gap-2 pt-2">
              <button className="btn btn-secondary" type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" type="submit" disabled={pending || editRoles.length === 0}>
                {pending ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
