import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import { navLinksFor, roleNames } from "../auth/access";
import type { AppUser } from "../auth/types";
import Logo from "./Logo";

export type { AppUser };

export default function AppShell({
  user,
  onLogout,
  children,
}: {
  user: AppUser;
  onLogout: () => void;
  children: ReactNode;
}) {
  const initial = (user.name || user.email || "?").slice(0, 1).toUpperCase();
  const links = navLinksFor(user);
  const tenantLabel = user.is_super_admin ? "Platform" : user.tenant_name || user.tenant_slug;
  const roleLabel = roleNames(user)[0];
  const displayName = user.name || user.email;

  return (
    <div className="flex min-h-screen flex-col bg-background font-sans text-body-md text-on-surface">
      <header className="sticky top-0 z-40 border-b border-outline-variant/30 bg-surface-lowest">
        <div className="mx-auto flex w-full min-h-14 max-w-[96rem] flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2 sm:px-6 lg:flex-nowrap">
          <div className="flex shrink-0 items-center gap-2">
            <Logo className="h-8 w-8 shrink-0" />
            <span className="whitespace-nowrap text-headline-sm tracking-tight">RAG Platform</span>
          </div>
          <nav className="order-last flex w-full flex-wrap content-start items-center gap-x-0.5 gap-y-1 lg:order-none lg:w-auto lg:min-w-0 lg:flex-1">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  isActive
                    ? "whitespace-nowrap rounded px-2 py-1 text-label-md font-semibold text-on-surface bg-surface-container"
                    : "whitespace-nowrap rounded px-2 py-1 text-label-md text-on-variant hover:bg-surface-low hover:text-on-surface"
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {tenantLabel && (
              <span className="chip max-w-[11rem] truncate">
                <span className="status-dot" />
                {tenantLabel}
              </span>
            )}
            <span
              className="hidden max-w-[14rem] truncate text-body-sm font-medium text-on-variant lg:inline"
              title={user.email}
            >
              {displayName}
              {roleLabel ? ` · ${roleLabel}` : ""}
            </span>
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-[12px] font-medium text-on-primary">
              {initial}
            </span>
            <button className="shrink-0 px-1 py-0.5 text-label-md text-secondary hover:text-on-surface" type="button" onClick={onLogout}>
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-shell flex-1 flex-col px-6 py-6">{children}</main>
      <footer className="border-t border-outline-variant/30 px-6 py-3 text-[11px] text-on-variant">
        <div className="mx-auto flex max-w-shell items-center justify-between gap-3">
          <span>
            {user.is_super_admin
              ? "© RAG Platform · Super Admin"
              : "© RAG Platform · answers stay inside the documents you can read"}
          </span>
          <span className="inline-flex items-center gap-2 font-mono text-code-sm">
            v0.1.0
            <span className="chip">
              <span className="status-dot" />
              Operational
            </span>
          </span>
        </div>
      </footer>
    </div>
  );
}
