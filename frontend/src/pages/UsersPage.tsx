import { FormEvent, useEffect, useState } from "react";
import { asList, invitationsApi, rolesApi, usersApi } from "../api/client";
import { displayRoleList, formatWhen } from "../auth/access";
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

export default function UsersPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  const [openInvite, setOpenInvite] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState(false);

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
      const created = await invitationsApi.create({
        name: name.trim(),
        email: email.trim(),
        role_ids: selected,
        roles: roleNames,
      });
      const token = created?.invitation_token || created?.token;
      setBanner(token ? `Invitation sent. Token (dev): ${token}` : "Invitation sent.");
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

  function toggleRole(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <section className="space-y-5">
      <PageHeader
        title="Users"
        subtitle="Invite people to this tenant and disable accounts that should no longer sign in."
        actions={
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
        }
      />
      {error && <Alert>{error}</Alert>}
      {banner && <Alert tone="ok">{banner}</Alert>}
      <div className="panel">
        <div className="table-head grid-cols-[1.3fr_1.4fr_1.2fr_auto_auto_auto]">
          <span>Name</span>
          <span>Email</span>
          <span>Roles</span>
          <span>Status</span>
          <span>Last login</span>
          <span />
        </div>
        <ul>
          {users.map((user) => {
            const status = (user.status || "active").toLowerCase();
            const disabled = status === "disabled" || status === "inactive";
            return (
              <li key={user.id} className="table-row grid-cols-[1.3fr_1.4fr_1.2fr_auto_auto_auto]">
                <span className="font-medium">{user.name || "—"}</span>
                <span className="truncate">{user.email}</span>
                <span className="truncate text-on-variant">{displayRoleList(user.roles)}</span>
                <StatusPill status={user.status || "active"} />
                <span className="font-mono text-code-sm text-on-variant">{formatWhen(user.last_login_at)}</span>
                <button className="link-action" type="button" onClick={() => toggleStatus(user)}>
                  {disabled ? "Enable" : "Disable"}
                </button>
              </li>
            );
          })}
          {users.length === 0 && <li className="px-4 py-8 text-center text-body-md text-on-variant">No users yet.</li>}
        </ul>
      </div>

      {openInvite && (
        <Modal title="Invite User" onClose={() => setOpenInvite(false)}>
          <form className="mt-4 space-y-3 text-sm" onSubmit={onInvite}>
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
                    <input type="checkbox" checked={selected.includes(role.id)} onChange={() => toggleRole(role.id)} />
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
    </section>
  );
}
