import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { asList, chatApi, docs } from "../api/client";
import { formatWhen, roleNames } from "../auth/access";
import { useCurrentUser } from "../auth/CurrentUserContext";

type Doc = {
  id: string;
  title: string;
  status?: string;
  acl?: { visibility?: string; allowed_roles?: string[] };
  owner_user_id?: string | null;
};

type Conversation = {
  id: string;
  title?: string | null;
  updated_at?: string | null;
};

export default function HomePage() {
  const user = useCurrentUser();
  const roles = roleNames(user);
  const [items, setItems] = useState<Doc[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    setLoading(true);
    try {
      const [docResult, chatResult] = await Promise.allSettled([docs.list(), chatApi.conversations()]);
      if (docResult.status === "fulfilled") setItems(asList<Doc>(docResult.value));
      else setItems([]);
      if (chatResult.status === "fulfilled") setConversations(asList<Conversation>(chatResult.value));
      else setConversations([]);
      if (docResult.status === "rejected" && chatResult.status === "rejected") {
        const reason = docResult.reason;
        setError(reason instanceof Error ? reason.message : "Could not load this workspace.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!user) return;
    load().catch(() => undefined);
  }, [user?.email, user?.tenant_slug]);

  const name = user?.name || user?.email || "there";
  const roleLabel = roles[0] || "Member";
  const onlyMe = items.filter((d) => visibilityLabel(d.acl) === "Only me").length;
  const everyone = items.filter((d) => d.acl?.visibility === "tenant").length;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="page-kicker">
            {greeting()}, {name.split(" ")[0]}
          </p>
          <h1 className="page-title">{user?.tenant_name || "Workspace"}</h1>
          <p className="page-sub">
            {roleLabel}
            {user?.tenant_name ? ` · ${user.tenant_name}` : ""}. Counts below are files you are allowed to read.
          </p>
        </div>
        <Link className="btn btn-primary" to="/?fresh=1">
          Ask a question
        </Link>
      </div>

      {error && (
        <div className="banner-error">
          <span>{error}</span>
          <button className="ml-2 font-medium underline" type="button" onClick={() => load()}>
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="panel px-4 py-8 text-body-md text-on-variant">Loading your workspace…</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="You can read" value={String(items.length)} />
            <Metric label="Only me" value={String(onlyMe)} />
            <Metric label="Everyone in tenant" value={String(everyone)} />
            <Metric label="Recent questions" value={String(conversations.length)} />
          </div>

          <div className="rounded-xl border border-outline-variant/50 bg-surface-lowest p-4 shadow-card">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="max-w-2xl">
                <p className="text-label-sm font-medium uppercase tracking-[0.02em] text-on-variant">Next</p>
                <h2 className="mt-1 text-headline-sm">Continue in chat</h2>
                <p className="mt-1 text-body-sm text-on-variant">
                  Questions stay in your history. Citations come only from documents you can read.
                </p>
              </div>
              <Link className="btn btn-primary" to="/?fresh=1">
                Open chat
              </Link>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="panel">
              <div className="flex items-center justify-between border-b border-outline-variant/30 px-4 py-3">
                <h2 className="text-headline-sm">Recent questions</h2>
                <Link className="link-action" to="/">
                  Open chat
                </Link>
              </div>
              {conversations.length === 0 ? (
                <p className="px-4 py-6 text-body-sm text-on-variant">
                  No questions yet. Ask one and it will stay in this list for the next visit.
                </p>
              ) : (
                <ul>
                  {conversations.slice(0, 5).map((c) => (
                    <li key={c.id} className="border-b border-outline-variant/20 last:border-0">
                      <Link className="block px-4 py-3 hover:bg-surface-low" to={`/?c=${encodeURIComponent(c.id)}`}>
                        <span className="block font-medium">{c.title || "Untitled question"}</span>
                        <span className="text-body-sm text-on-variant">{formatWhen(c.updated_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="panel">
              <div className="flex items-center justify-between border-b border-outline-variant/30 px-4 py-3">
                <h2 className="text-headline-sm">Documents you can read</h2>
                <Link className="link-action" to="/documents">
                  All documents
                </Link>
              </div>
              {items.length === 0 ? (
                <p className="px-4 py-6 text-body-sm text-on-variant">
                  No documents yet. Upload one from Documents and choose who can see it.
                </p>
              ) : (
                <ul>
                  {items.slice(0, 5).map((d) => (
                    <li key={d.id} className="border-b border-outline-variant/20 last:border-0">
                      <Link
                        className="flex items-start justify-between gap-3 px-4 py-3 hover:bg-surface-low"
                        to={`/documents?focus=${encodeURIComponent(d.id)}`}
                      >
                        <span>
                          <span className="block font-medium">{d.title}</span>
                          <span className="text-body-sm text-on-variant">
                            {d.owner_user_id && user?.user_id && d.owner_user_id === user.user_id
                              ? "Uploaded by you"
                              : "Shared with you"}
                            {" · "}
                            {d.status || "indexed"}
                          </span>
                        </span>
                        <span className="chip shrink-0">{visibilityLabel(d.acl)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

function visibilityLabel(acl: Doc["acl"]): string {
  if (!acl) return "Only me";
  if (acl.visibility === "tenant") return "Everyone in this tenant";
  const roles = acl.allowed_roles || [];
  if (roles.length === 0) return "Only me";
  return roles.join(", ");
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}
