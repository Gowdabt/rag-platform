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
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6 font-sans text-body-md text-on-surface">
      <div className="w-full max-w-md">
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
