import type { AppUser } from "./types";

export type NavLinkItem = {
  to: string;
  label: string;
  end?: boolean;
};

export function permissionCodes(user: AppUser | null | undefined): string[] {
  return user?.permissions || [];
}

export function roleNames(user: AppUser | null | undefined): string[] {
  return (user?.roles || [])
    .map((role) => (typeof role === "string" ? role : role.name || role.slug || ""))
    .filter(Boolean);
}

export function hasAnyPermission(user: AppUser | null | undefined, codes: string[]): boolean {
  if (!user) return false;
  const have = new Set(permissionCodes(user));
  return codes.some((code) => have.has(code));
}

export function isSuperAdmin(user: AppUser | null | undefined): boolean {
  return Boolean(user?.is_super_admin);
}

export function navLinksFor(user: AppUser): NavLinkItem[] {
  if (isSuperAdmin(user)) {
    return [
      { to: "/platform", label: "Dashboard", end: true },
      { to: "/platform/tenants", label: "Tenants" },
      { to: "/platform/config", label: "Platform Configuration" },
      { to: "/platform/audit", label: "Audit Logs" },
    ];
  }
  const links: NavLinkItem[] = [];
  if (hasAnyPermission(user, ["ai.chat", "document:read", "conversation:read"])) {
    links.push({ to: "/", label: "Chat", end: true });
  }
  if (hasAnyPermission(user, ["folders.view", "document:read"])) {
    links.push({ to: "/data", label: "Data" });
  }
  if (hasAnyPermission(user, ["document:read", "document:write"])) {
    links.push({ to: "/documents", label: "Documents" });
  }
  if (hasAnyPermission(user, ["source:manage"])) {
    links.push({ to: "/sources", label: "Sources" });
  }
  if (hasAnyPermission(user, ["users.view", "user:manage"])) {
    links.push({ to: "/admin/users", label: "Users" });
  }
  if (hasAnyPermission(user, ["roles.view", "user:manage"])) {
    links.push({ to: "/admin/roles", label: "Roles" });
  }
  if (hasAnyPermission(user, ["ai.configuration.view", "config:write", "config:read"])) {
    links.push({ to: "/admin/ai", label: "AI Configuration" });
  }
  if (hasAnyPermission(user, ["audit.view", "audit:read"])) {
    links.push({ to: "/admin/audit", label: "Audit" });
  }
  if (hasAnyPermission(user, ["config:read"])) {
    links.push({ to: "/admin", label: "Settings" });
  }
  return links;
}

export function defaultHome(user: AppUser): string {
  if (isSuperAdmin(user)) return "/platform";
  return navLinksFor(user)[0]?.to || "";
}

export function formatWhen(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

export function displayRoleList(roles: unknown): string {
  if (!roles) return "—";
  if (Array.isArray(roles)) {
    const names = roles
      .map((role) => {
        if (typeof role === "string") return role;
        if (role && typeof role === "object") {
          const rec = role as { name?: string; slug?: string };
          return rec.name || rec.slug || "";
        }
        return "";
      })
      .filter(Boolean);
    return names.join(", ") || "—";
  }
  if (typeof roles === "string") return roles;
  return "—";
}

export const PERMISSION_GROUPS = ["Users", "Folders", "Documents", "AI", "Admin"] as const;
export type PermissionGroup = (typeof PERMISSION_GROUPS)[number];

export function permissionGroup(code: string, provided?: string | null): PermissionGroup {
  const raw = (provided || code).toLowerCase();
  if (raw.startsWith("user") || raw.includes("users")) return "Users";
  if (raw.startsWith("folder") || raw.includes("folders")) return "Folders";
  if (raw.startsWith("document") || raw.includes("documents")) return "Documents";
  if (raw.startsWith("ai") || raw.includes("conversation") || raw.includes("chat") || raw.includes("rag")) {
    return "AI";
  }
  return "Admin";
}
