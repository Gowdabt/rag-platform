import type { ReactNode } from "react";

export default function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-30 flex items-start justify-center p-4 pt-16" style={{ background: "var(--color-overlay)" }}>
      <div
        className={`max-h-[80vh] w-full overflow-auto rounded-xl border border-outline-variant bg-surface-lowest p-5 shadow-rest ${
          wide ? "max-w-2xl" : "max-w-xl"
        }`}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-headline-sm">{title}</h2>
          <button className="btn btn-ghost h-8 px-2" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
