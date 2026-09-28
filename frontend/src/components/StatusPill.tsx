export default function StatusPill({ status }: { status?: string | null }) {
  const value = status || "—";
  const s = value.toLowerCase();
  const ok = s === "active" || s === "ready" || s === "completed" || s === "enabled" || s === "healthy" || s === "connected";
  const warn = s === "invited" || s === "pending" || s === "suspended" || s === "paused" || s === "auth_expired";
  const bad = s.includes("fail") || s === "disabled" || s === "inactive" || s === "revoked";
  const palette = ok
    ? { bg: "var(--color-healthy-bg)", fg: "var(--color-healthy-fg)", dot: "var(--color-success)" }
    : bad
      ? { bg: "var(--color-failed-bg)", fg: "var(--color-failed-fg)", dot: "var(--color-error)" }
      : warn
        ? { bg: "var(--color-warning-bg)", fg: "var(--color-warning-fg)", dot: "#d97706" }
        : { bg: "var(--color-surface-container-low)", fg: "var(--color-on-surface-variant)", dot: "var(--color-secondary)" };
  return (
    <span
      className="inline-flex h-[22px] items-center gap-1.5 rounded-full px-2 text-[11px] font-medium"
      style={{ background: palette.bg, color: palette.fg }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: palette.dot }} />
      {value}
    </span>
  );
}
