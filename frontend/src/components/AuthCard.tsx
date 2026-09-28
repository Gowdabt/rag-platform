import type { ReactNode } from "react";
import Logo from "./Logo";

export default function AuthCard({
  title = "RAG Platform",
  subtitle,
  children,
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const desktop = Boolean(window.ragDesktop);
  const macDesktop = desktop && window.ragDesktop?.platform === "darwin";
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6 font-sans text-body-md text-on-surface">
      {desktop && (
        <div
          className="desktop-drag fixed inset-x-0 top-0 h-11"
          style={macDesktop ? { paddingLeft: 88 } : undefined}
          aria-hidden
        />
      )}
      <div className="desktop-no-drag w-full max-w-md">
        <p className="mb-3 text-center font-mono text-code-sm uppercase tracking-[0.16em] text-on-variant">
          RAG Platform desktop client
        </p>
        <div className="rounded-xl bg-surface-lowest p-8 shadow-card">
          <div className="flex flex-col items-center space-y-2 text-center">
            <div className="flex items-center justify-center gap-3">
              <Logo className="h-8 w-8" />
              <h1 className="text-headline-lg tracking-tight">{title}</h1>
            </div>
            {subtitle && <p className="max-w-xs text-body-md text-on-variant">{subtitle}</p>}
          </div>
          {children}
        </div>
        <p className="mt-6 text-center font-mono text-code-sm text-on-variant">
          Self-hosted enterprise RAG · L3 tenant isolation · zero egress
        </p>
      </div>
    </div>
  );
}
