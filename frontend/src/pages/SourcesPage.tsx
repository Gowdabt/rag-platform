import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { sourcesApi } from "../api/client";

type CatalogItem = {
  id: string;
  name: string;
  description: string;
  authentication: string;
  mock?: boolean;
  configured?: boolean;
  oauth_group?: string;
  capabilities?: { browse?: boolean; subscribe?: boolean };
};

type OauthClientStatus = {
  client_id: string;
  configured: boolean;
  from_env: boolean;
  has_secret: boolean;
};

type OauthStatus = {
  clients: Record<string, OauthClientStatus>;
  redirect_uris: string[];
};

type Subscription = {
  id: string;
  external_location_name: string;
  status: string;
  schedule: string;
  last_sync_at?: string | null;
  last_error?: string | null;
};

type Source = {
  id: string;
  name: string;
  connector_type: string;
  status: string;
  account_label?: string | null;
  last_synced_at?: string | null;
  last_error?: string | null;
  document_count?: number;
  subscriptions: Subscription[];
};

type BrowseItem = {
  id: string;
  name: string;
  path?: string;
  kind: "folder" | "file";
  child_count?: number;
};

type HostBrowse = {
  path: string | null;
  parent: string | null;
  at_roots: boolean;
  items: BrowseItem[];
};

type Step = "closed" | "pick" | "config" | "oauth-config" | "auth" | "browse" | "configure" | "working";

export default function SourcesPage() {
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>("closed");
  const [selected, setSelected] = useState<CatalogItem | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [folder, setFolder] = useState<BrowseItem | null>(null);
  const [children, setChildren] = useState<BrowseItem[]>([]);
  const [includeSub, setIncludeSub] = useState(true);
  const [schedule, setSchedule] = useState("every_30_minutes");
  const [busy, setBusy] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [hostPath, setHostPath] = useState<string | null>(null);
  const [hostParent, setHostParent] = useState<string | null>(null);
  const [hostAtRoots, setHostAtRoots] = useState(true);
  const [hostItems, setHostItems] = useState<BrowseItem[]>([]);
  const [bucket, setBucket] = useState("");
  const [prefix, setPrefix] = useState("");
  const [s3Endpoint, setS3Endpoint] = useState("");
  const [s3Access, setS3Access] = useState("");
  const [s3Secret, setS3Secret] = useState("");
  const [oauthStatus, setOauthStatus] = useState<OauthStatus | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [folderUrl, setFolderUrl] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();

  async function refresh() {
    const [c, s, o] = await Promise.all([
      sourcesApi.catalog(),
      sourcesApi.list(),
      sourcesApi.oauthClients().catch(() => null),
    ]);
    setCatalog(c);
    setSources(s);
    if (o) setOauthStatus(o);
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setSchedule(selected.authentication === "oauth2" || selected.id === "local_fs" ? "every_30_minutes" : "manual");
  }, [selected?.id]);

  useEffect(() => {
    const oauthError = searchParams.get("error");
    const oauthDesc = searchParams.get("error_description");
    if (oauthError) {
      setError(oauthDesc || `Sign-in was cancelled (${oauthError}).`);
      setSearchParams({});
      return;
    }
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    if (!code || !state) return;
    setBusy("Finishing OAuth…");
    setStep("auth");
    sourcesApi
      .oauthCallback(code, state)
      .then(async (connected: { id: string; has_subscriptions?: boolean }) => {
        setSearchParams({});
        setBusy("");
        if (connected.has_subscriptions) {
          await refresh();
          resetWizard();
          return;
        }
        setSourceId(connected.id);
        setStep("browse");
      })
      .catch((e) => {
        setError(String(e));
        setBusy("");
        setStep("closed");
        setSearchParams({});
      });
  }, [searchParams, setSearchParams]);

  function resetWizard() {
    setStep("closed");
    setSelected(null);
    setSourceId(null);
    setFolder(null);
    setChildren([]);
    setBusy("");
    setRootPath("");
    setHostPath(null);
    setHostParent(null);
    setHostAtRoots(true);
    setHostItems([]);
    setBucket("");
    setPrefix("");
    setS3Endpoint("");
    setS3Access("");
    setS3Secret("");
    setClientId("");
    setClientSecret("");
    setFolderUrl("");
  }

  async function startOAuth(item: CatalogItem, sourceId?: string) {
    setBusy("Opening the provider sign-in page…");
    setStep("auth");
    try {
      const started = await sourcesApi.oauthStart(item.id, sourceId);
      const url = started.authorization_url as string;
      if (url.includes("mock-granted")) {
        const parsed = new URL(url, window.location.origin);
        const connected = await sourcesApi.oauthCallback(parsed.searchParams.get("code") || "mock-granted", started.state);
        setBusy("");
        if (connected.has_subscriptions) {
          await refresh();
          resetWizard();
          return;
        }
        setSourceId(connected.id);
        setStep("browse");
        return;
      }
      window.location.assign(url);
    } catch (e) {
      const msg = String(e);
      setBusy("");
      if (/not configured/i.test(msg)) {
        const group = item.oauth_group;
        const status = group ? oauthStatus?.clients?.[group] : undefined;
        setClientId(status?.client_id || "");
        setClientSecret("");
        setError("");
        setStep("oauth-config");
        return;
      }
      setError(msg);
      setStep("closed");
    }
  }

  async function loginSource(item: CatalogItem, sourceId?: string) {
    setSelected(item);
    setError("");
    await startOAuth(item, sourceId);
  }

  async function saveOauthAndLogin() {
    if (!selected?.oauth_group) return;
    if (!clientId.trim() || !clientSecret.trim()) {
      setError("Enter both the OAuth client ID and client secret.");
      return;
    }
    setBusy("Saving OAuth client…");
    try {
      const saved = await sourcesApi.saveOauthClients({
        [selected.oauth_group]: { client_id: clientId.trim(), client_secret: clientSecret.trim() },
      });
      setOauthStatus(saved);
      await startOAuth(selected);
    } catch (e) {
      setBusy("");
      setError(String(e));
    }
  }

  async function connectProvider(item: CatalogItem) {
    setSelected(item);
    setError("");
    if (item.authentication === "oauth2") {
      await loginSource(item);
      return;
    }
    setStep("config");
  }

  async function connectConfigured() {
    if (!selected) return;
    setBusy("Connecting…");
    try {
      const config: Record<string, string> = {};
      if (selected.id === "local_fs") {
        if (!rootPath.trim()) throw new Error("Enter a folder path the API server can read.");
        config.root_path = rootPath.trim();
      }
      if (selected.id === "s3") {
        if (bucket.trim()) config.bucket = bucket.trim();
        if (prefix.trim()) config.prefix = prefix.trim();
        if (s3Endpoint.trim()) config.endpoint_url = s3Endpoint.trim();
        if (s3Access.trim()) config.access_key = s3Access.trim();
        if (s3Secret.trim()) config.secret_key = s3Secret.trim();
      }
      const created = await sourcesApi.create(selected.id, selected.name, config);
      setSourceId(created.id);
      setBusy("");
      setStep("browse");
    } catch (e) {
      setBusy("");
      setError(String(e));
    }
  }

  async function openBrowse(id: string) {
    setBusy("");
    const items = await sourcesApi.children(id, "root");
    setChildren(items);
    setFolder({ id: "root", name: "Root", kind: "folder" });
  }

  useEffect(() => {
    if (step === "browse" && sourceId) {
      openBrowse(sourceId).catch((e) => setError(String(e)));
    }
  }, [step, sourceId]);

  useEffect(() => {
    if (step !== "config" || selected?.id !== "local_fs") return;
    let cancelled = false;
    setBusy("Loading folders…");
    sourcesApi
      .browseLocal(hostPath || undefined)
      .then((data: HostBrowse) => {
        if (cancelled) return;
        setHostItems(data.items || []);
        setHostParent(data.parent);
        setHostAtRoots(Boolean(data.at_roots));
        setBusy("");
      })
      .catch((e) => {
        if (cancelled) return;
        setBusy("");
        setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [step, selected, hostPath]);

  async function addFolder(src: Source) {
    const item = catalog.find((c) => c.id === src.connector_type);
    if (!item) return;
    setSelected(item);
    setSourceId(src.id);
    setFolder(null);
    setChildren([]);
    setFolderUrl("");
    setError("");
    setStep("browse");
  }

  async function openFromUrl() {
    if (!sourceId || !folderUrl.trim()) return;
    setBusy("Opening shared folder…");
    try {
      const loc = await sourcesApi.resolveLocation(sourceId, folderUrl.trim());
      const item: BrowseItem = { id: loc.id, name: loc.name, path: loc.path, kind: "folder" };
      setFolder(item);
      setChildren(await sourcesApi.children(sourceId, loc.id));
      setBusy("");
    } catch (e) {
      setBusy("");
      setError(String(e));
    }
  }

  async function enterFolder(item: BrowseItem) {
    if (!sourceId || item.kind !== "folder") return;
    setFolder(item);
    setChildren(await sourcesApi.children(sourceId, item.id));
  }

  async function finishSubscribe() {
    if (!folder) return;
    setBusy("Subscribing and syncing…");
    setStep("working");
    try {
      let id = sourceId;
      if (!id && selected?.id === "local_fs") {
        const created = await sourcesApi.create(selected.id, folder.name, { root_path: rootPath || folder.path || folder.id });
        id = created.id;
        setSourceId(id);
      }
      if (!id) return;
      await sourcesApi.subscribe(id, {
        location_id: selected?.id === "local_fs" ? "root" : folder.id,
        location_name: folder.name,
        include_subfolders: includeSub,
        schedule,
      });
      await refresh();
      resetWizard();
    } catch (e) {
      setError(String(e));
      setStep("configure");
      setBusy("");
    }
  }

  async function syncNow(subId: string) {
    setBusy("Syncing…");
    try {
      const run = await sourcesApi.sync(subId);
      await refresh();
      const added = run.files_added ?? 0;
      const updated = run.files_updated ?? 0;
      const removed = run.files_deleted ?? 0;
      setBusy(`Last sync: ${added} added, ${updated} updated, ${removed} removed from the index.`);
    } catch (e) {
      setBusy("");
      setError(String(e));
    }
  }

  const visibleSources = sources.filter(
    (src) => !src.connector_type.startsWith("mock_") && src.status !== "disconnected",
  );

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Sources</h1>
          <p className="page-sub">
            Connect a knowledge source, pick a folder, and sync it into this workspace.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => {
            setError("");
            setStep("pick");
          }}
        >
          + Add Source
        </button>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <MiniStat label="Connected" value={String(visibleSources.length)} />
        <MiniStat label="Subscriptions" value={String(visibleSources.reduce((n, s) => n + (s.subscriptions?.length || 0), 0))} />
        <MiniStat label="Indexed files" value={String(visibleSources.reduce((n, s) => n + (s.document_count || 0), 0))} />
        <MiniStat
          label="Needs attention"
          value={String(visibleSources.filter((s) => s.status === "auth_expired" || s.last_error).length)}
        />
      </div>

      {error && <p className="mt-3 rounded-lg bg-error-container/40 px-3 py-2 text-sm text-on-error-container">{error}</p>}
      {busy && <p className="mt-3 text-sm text-on-variant">{busy}</p>}

      <div className="mt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-on-variant">Sign in to a source</h2>
          <p className="mt-1 text-[13px] text-on-variant">
          Log in opens Google, Microsoft, or Dropbox at runtime. OAuth client values are saved encrypted for this tenant — they are not required in .env before start.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {catalog
            .filter((item) => !item.mock && !item.id.startsWith("mock_"))
            .map((item) => (
              <article
                key={item.id}
                className="flex items-start justify-between gap-3 rounded-xl border border-outline-variant/50 bg-surface-lowest p-4 shadow-card"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{item.name}</h3>
                    {item.authentication === "oauth2" && (
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] ${
                          item.configured ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {item.configured ? "Ready to sign in" : "Save client at runtime"}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-on-variant">{item.description}</p>
                  {item.authentication === "oauth2" && <OauthConsoleLinks group={item.oauth_group} variant="card" />}
                </div>
                {item.authentication === "oauth2" ? (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => loginSource(item)}
                  >
                    Log in
                  </button>
                ) : (
                  <button
                    type="button"
                    className="shrink-0 rounded-lg border border-outline-variant px-3 py-2 text-[12px] font-medium"
                    onClick={() => connectProvider(item)}
                  >
                    Connect
                  </button>
                )}
              </article>
            ))}
        </div>
      </div>

      <div className="mt-8 space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-on-variant">Connected</h2>
        {visibleSources.length === 0 && (
          <div className="rounded-xl border border-dashed border-outline-variant bg-surface-lowest px-6 py-10 text-center text-sm text-on-variant">
            No connected sources yet. Add a local folder the API can read, or connect Drive / OneDrive / Dropbox / S3.
          </div>
        )}
        {visibleSources.map((src) => (
          <article key={src.id} className="rounded-xl border border-outline-variant/50 bg-surface-lowest p-4 shadow-card">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold">{src.name}</h2>
                  <span className="rounded-full bg-surface-container px-2 py-0.5 font-mono text-[11px] text-on-variant">
                    {src.connector_type}
                  </span>
                  <StatusPill status={src.status} />
                </div>
                <p className="mt-1 text-sm text-on-variant">
                  {src.account_label ? `${src.account_label} · ` : ""}
                  {src.document_count ?? 0} documents
                  {src.last_synced_at ? ` · last sync ${new Date(src.last_synced_at).toLocaleString()}` : ""}
                </p>
                {src.last_error && <p className="mt-1 text-sm text-error">{src.last_error}</p>}
              </div>
              <div className="flex shrink-0 gap-2">
                {src.status === "auth_expired" && (
                  <button
                    type="button"
                    className="rounded-lg border border-outline-variant px-3 py-1.5 text-[12px]"
                    onClick={() => {
                      const item = catalog.find((c) => c.id === src.connector_type);
                      if (item) loginSource(item, src.id);
                    }}
                  >
                    Log in again
                  </button>
                )}
                <button
                  className="text-sm text-on-variant underline"
                  onClick={() =>
                    sourcesApi
                      .disconnect(src.id)
                      .then(refresh)
                      .catch((e) => setError(String(e)))
                  }
                >
                  Disconnect
                </button>
              </div>
            </div>
            <ul className="mt-3 space-y-2">
              {(src.subscriptions || []).map((sub) => (
                <li key={sub.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-low px-3 py-2 text-sm">
                  <div>
                    <span className="font-medium">{sub.external_location_name}</span>
                    <span className="ml-2 text-on-variant">
                      {sub.status} · {sub.schedule}
                      {sub.last_sync_at ? ` · last sync ${new Date(sub.last_sync_at).toLocaleString()}` : ""}
                    </span>
                    {sub.last_error && <div className="text-error">{sub.last_error}</div>}
                  </div>
                  <div className="flex gap-2">
                    <button className="rounded-lg border border-outline-variant px-2 py-1" onClick={() => syncNow(sub.id)}>
                      Sync now
                    </button>
                    <button
                      className="rounded-lg border border-outline-variant px-2 py-1"
                      onClick={() =>
                        sourcesApi
                          .patchSubscription(sub.id, { status: sub.status === "paused" ? "active" : "paused" })
                          .then(refresh)
                      }
                    >
                      {sub.status === "paused" ? "Resume" : "Pause"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            {(src.connector_type === "google_drive" ||
              src.connector_type === "onedrive" ||
              src.connector_type === "sharepoint" ||
              src.connector_type === "dropbox") && (
              <button
                type="button"
                className="mt-3 text-[12px] text-on-variant underline"
                onClick={() => addFolder(src)}
              >
                Add folder
              </button>
            )}
          </article>
        ))}
      </div>

      {step !== "closed" && (
        <div className="fixed inset-0 z-20 flex items-start justify-center bg-primary-container/40 p-4 pt-16 backdrop-blur-[2px]">
          <div className="max-h-[80vh] w-full max-w-xl overflow-auto rounded-xl bg-surface-lowest p-5 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                {selected ? `Connect ${selected.name}` : "Add a knowledge source"}
              </h2>
              <button className="text-sm text-on-variant" onClick={() => {
                if (step === "configure" && selected?.id === "local_fs" && !sourceId) {
                  setStep("config");
                  return;
                }
                resetWizard();
              }}>
                {step === "browse" || step === "configure" ? "Change" : "Cancel"}
              </button>
            </div>
            {step === "pick" && (
              <div className="mt-4 grid gap-2">
        {catalog.filter((item) => !item.mock && !item.id.startsWith("mock_")).map((item) => (
                  <div
                    key={item.id}
                    className="rounded-lg border border-outline-variant/70 px-3 py-3 text-left hover:border-secondary"
                  >
                    <button type="button" className="w-full text-left" onClick={() => connectProvider(item)}>
                      <div className="font-medium">{item.name}</div>
                      <div className="text-sm text-on-variant">{item.description}</div>
                      {item.authentication === "oauth2" && item.configured === false && (
                        <div className="mt-1 text-xs text-amber-700">Paste the OAuth client on Log in, then sign in.</div>
                      )}
                    </button>
                    {item.authentication === "oauth2" && <OauthConsoleLinks group={item.oauth_group} variant="card" />}
                  </div>
                ))}
              </div>
            )}
            {step === "oauth-config" && selected && (
              <div className="mt-4 space-y-3 text-sm">
                <p>
                  Log in will open <strong>{providerLoginName(selected.oauth_group)}</strong>, ask for Drive/folder access, then save that session here.
                  Google/Microsoft/Dropbox will not show that page until this product has an OAuth web client (one-time).
                </p>
                <OauthConsoleLinks group={selected.oauth_group} variant="panel" />
                <p className="text-on-variant">{oauthSetupHelp(selected.oauth_group)}</p>
                <label className="block">
                  Client ID
                  <input
                    className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <label className="block">
                  Client secret
                  <input
                    className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3"
                    type="password"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <div>
                  <div className="text-[12px] font-medium text-on-variant">Redirect URIs to allow in the provider console</div>
                  <ul className="mt-1 space-y-1 font-mono text-[12px]">
                    {(oauthStatus?.redirect_uris || [`${window.location.origin}/sources`]).map((uri) => (
                      <li key={uri} className="rounded-md bg-surface-low px-2 py-1">
                        {uri}
                      </li>
                    ))}
                  </ul>
                </div>
                <button type="button" className="btn btn-primary" onClick={saveOauthAndLogin}>
                  Continue to {providerLoginName(selected.oauth_group)}
                </button>
              </div>
            )}
            {step === "config" && selected && (
              <div className="mt-4 space-y-3 text-sm">
                {selected.id === "local_fs" && (
                  <div>
                    <p className="text-on-variant">
                      Open a location to browse inside it, then Select the specific folder to index.
                      Selecting a top-level row indexes that whole folder.
                    </p>
                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="min-w-0 truncate font-medium">
                        {hostAtRoots ? "This computer" : hostPath?.split("/").filter(Boolean).slice(-3).join(" / ")}
                      </div>
                      {!hostAtRoots && (
                        <button
                          type="button"
                          className="shrink-0 text-[12px] text-on-variant underline"
                          onClick={() => setHostPath(hostParent)}
                        >
                          Up
                        </button>
                      )}
                    </div>
                    <div className="mt-2 max-h-72 space-y-1 overflow-auto">
                      {hostItems.length === 0 && !busy && (
                        <p className="rounded-lg bg-surface-low px-3 py-2 text-on-variant">
                          No folders here. Add another allow-list path in Admin runtime settings if you need a different disk location.
                        </p>
                      )}
                      {hostItems.map((item) => (
                        <div
                          key={item.id}
                          className="flex w-full items-center justify-between gap-2 rounded-lg border border-outline-variant/60 px-3 py-2 text-left"
                        >
                          <button
                            type="button"
                            className="min-w-0 flex-1 text-left"
                            onClick={() => {
                              if (item.kind !== "folder") return;
                              setError("");
                              setHostPath(item.path || item.id);
                            }}
                          >
                            {item.kind === "folder" ? "📁" : "📄"} {item.name}
                            {item.child_count != null ? (
                              <span className="ml-2 text-[11px] text-on-variant">{item.child_count} items</span>
                            ) : null}
                          </button>
                          {item.kind === "folder" && (
                            <div className="flex shrink-0 gap-1">
                              <button
                                type="button"
                                className="rounded-md border border-outline-variant px-2 py-1 text-[11px]"
                                onClick={() => {
                                  setError("");
                                  setHostPath(item.path || item.id);
                                }}
                              >
                                Open
                              </button>
                              <button
                                type="button"
                                className="btn btn-primary h-7 px-2 text-[11px]"
                                onClick={() => {
                                  setRootPath(item.path || item.id);
                                  setFolder(item);
                                  setStep("configure");
                                }}
                              >
                                Select
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                    {!hostAtRoots && hostPath && (
                      <button
                        type="button"
                        className="btn btn-primary mt-3"
                        onClick={() => {
                          const name = hostPath.split("/").filter(Boolean).pop() || hostPath;
                          setRootPath(hostPath);
                          setFolder({ id: hostPath, name, path: hostPath, kind: "folder" });
                          setStep("configure");
                        }}
                      >
                        Use this folder
                      </button>
                    )}
                  </div>
                )}
                {selected.id === "s3" && (
                  <>
                    <label className="block">
                      Bucket
                      <input className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3" value={bucket} onChange={(e) => setBucket(e.target.value)} placeholder="Uses S3_BUCKET if empty" />
                    </label>
                    <label className="block">
                      Prefix
                      <input className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3" value={prefix} onChange={(e) => setPrefix(e.target.value)} />
                    </label>
                    <label className="block">
                      Endpoint (MinIO / custom)
                      <input className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3" value={s3Endpoint} onChange={(e) => setS3Endpoint(e.target.value)} placeholder="Uses S3_ENDPOINT_URL if empty" />
                    </label>
                    <label className="block">
                      Access key
                      <input className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3" value={s3Access} onChange={(e) => setS3Access(e.target.value)} />
                    </label>
                    <label className="block">
                      Secret key
                      <input className="mt-1 h-9 w-full rounded-lg border border-outline-variant/70 px-3" type="password" value={s3Secret} onChange={(e) => setS3Secret(e.target.value)} />
                    </label>
                    <button type="button" className="btn btn-primary" onClick={connectConfigured}>
                      Connect and browse
                    </button>
                  </>
                )}
              </div>
            )}
            {step === "auth" && <p className="mt-4 text-sm text-on-variant">{busy || "Authenticating…"}</p>}
            {step === "browse" && (
              <div className="mt-4">
                {selected?.id === "google_drive" && (
                  <div className="mb-4 space-y-2">
                    <p className="text-sm text-on-variant">
                      Paste a shared team folder URL (anyone with access can open it in this Google account), or browse
                      Shared with me / Shared drives below.
                    </p>
                    <div className="flex gap-2">
                      <input
                        className="h-9 min-w-0 flex-1 rounded-lg border border-outline-variant/70 px-3 text-[13px]"
                        value={folderUrl}
                        onChange={(e) => setFolderUrl(e.target.value)}
                        placeholder="https://drive.google.com/drive/folders/..."
                      />
                      <button type="button" className="btn btn-primary shrink-0" onClick={openFromUrl}>
                        Open URL
                      </button>
                    </div>
                  </div>
                )}
                <p className="text-sm text-on-variant">Select a folder to index.</p>
                <div className="mt-2 space-y-1">
                  {children.map((item) => (
                    <div
                      key={item.id}
                      className="flex w-full items-center justify-between rounded-lg border border-outline-variant/60 px-3 py-2 text-left text-sm"
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => (item.kind === "folder" ? enterFolder(item) : undefined)}
                      >
                        {item.kind === "folder" ? "📁" : "📄"} {item.name}
                        {item.child_count != null ? (
                          <span className="ml-2 text-[11px] text-on-variant">{item.child_count} items</span>
                        ) : null}
                      </button>
                      {item.kind === "folder" && (
                        <button
                          type="button"
                          className="btn btn-primary h-7 px-2 text-[11px]"
                          onClick={() => {
                            setFolder(item);
                            setStep("configure");
                          }}
                        >
                          Select
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                {folder && (
                  <button
                    type="button"
                    className="btn btn-primary mt-3"
                    onClick={() => setStep("configure")}
                  >
                    Use {folder.name}
                  </button>
                )}
              </div>
            )}
            {step === "configure" && folder && (
              <div className="mt-4 space-y-3 text-sm">
                <p>
                  Folder: <strong>{folder.name}</strong>
                </p>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={includeSub} onChange={(e) => setIncludeSub(e.target.checked)} />
                  Include subfolders recursively
                </label>
                <label className="block">
                  Schedule
                  <select className="ml-2 rounded-lg border border-outline-variant px-2 py-1" value={schedule} onChange={(e) => setSchedule(e.target.value)}>
                    <option value="every_30_minutes">Every 30 minutes</option>
                    <option value="hourly">Hourly</option>
                    <option value="daily">Daily</option>
                    <option value="manual">Manual</option>
                  </select>
                </label>
                {schedule === "manual" && (
                  <p className="rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
                    Manual sync will keep deleted or replaced Drive files in answers until you click Sync now. Use a
                    schedule if this folder is the source of truth.
                  </p>
                )}
                <div className="flex justify-end gap-2 pt-2">
                  <button className="rounded-lg border border-outline-variant px-3 py-2" type="button" onClick={resetWizard}>
                    Cancel
                  </button>
                  <button className="btn btn-primary" onClick={finishSubscribe}>
                    Create subscription and sync
                  </button>
                </div>
              </div>
            )}
            {step === "working" && <p className="mt-4 text-sm">{busy}</p>}
          </div>
        </div>
      )}
    </section>
  );
}

function providerLoginName(group?: string) {
  if (group === "microsoft") return "Microsoft sign-in";
  if (group === "dropbox") return "Dropbox sign-in";
  return "Google sign-in";
}

type OauthConsole = {
  createLabel: string;
  createUrl: string;
  extras?: { label: string; url: string }[];
};

function oauthConsole(group?: string): OauthConsole | null {
  if (group === "google") {
    return {
      createLabel: "Create Google OAuth client",
      createUrl: "https://console.cloud.google.com/apis/credentials",
      extras: [
        { label: "Enable Drive API", url: "https://console.cloud.google.com/apis/library/drive.googleapis.com" },
        { label: "Add test users", url: "https://console.cloud.google.com/auth/audience" },
      ],
    };
  }
  if (group === "microsoft") {
    return {
      createLabel: "Create Microsoft OAuth client",
      createUrl: "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
    };
  }
  if (group === "dropbox") {
    return {
      createLabel: "Create Dropbox OAuth client",
      createUrl: "https://www.dropbox.com/developers/apps",
    };
  }
  return null;
}

function ExternalHref({ href, className, children }: { href: string; className?: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  );
}

function OauthConsoleLinks({ group, variant = "card" }: { group?: string; variant?: "card" | "panel" }) {
  const consoleInfo = oauthConsole(group);
  if (!consoleInfo) return null;
  if (variant === "panel") {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <ExternalHref
          href={consoleInfo.createUrl}
          className="inline-flex items-center rounded-lg border border-black px-3 py-2 text-[12px] font-medium"
        >
          {`${consoleInfo.createLabel} ↗`}
        </ExternalHref>
        {consoleInfo.extras?.map((item) => (
          <ExternalHref key={item.url} href={item.url} className="text-[12px] font-medium text-secondary underline">
            {`${item.label} ↗`}
          </ExternalHref>
        ))}
      </div>
    );
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
      <ExternalHref href={consoleInfo.createUrl} className="text-[12px] font-medium text-secondary underline">
        {`${consoleInfo.createLabel} ↗`}
      </ExternalHref>
      {consoleInfo.extras?.map((item) => (
        <ExternalHref key={item.url} href={item.url} className="text-[12px] text-on-variant underline">
          {`${item.label} ↗`}
        </ExternalHref>
      ))}
    </div>
  );
}

function oauthSetupHelp(group?: string) {
  if (group === "google") {
    return "Create an OAuth web client, enable the Drive API, add the redirect URIs below, and add your Gmail as a test user while the consent screen is in Testing.";
  }
  if (group === "microsoft") {
    return "Register a Web app in Microsoft Entra ID. One client covers OneDrive and SharePoint. Add Graph delegated permissions User.Read, Files.Read, Files.Read.All, Sites.Read.All, and offline_access, plus both redirect URIs.";
  }
  if (group === "dropbox") {
    return "Create an app in the Dropbox App Console, add both redirect URIs, and for scoped apps enable files.metadata.read, files.content.read, and account_info.read.";
  }
  return "Paste the OAuth client ID and secret from the provider console, then continue to sign in.";
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="text-[11px] font-medium uppercase tracking-wide text-on-variant">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const color =
    status === "connected"
      ? "bg-emerald-100 text-emerald-800"
      : status === "auth_expired"
        ? "bg-amber-100 text-amber-800"
        : status.includes("fail")
          ? "bg-red-100 text-red-800"
          : "bg-slate-100 text-slate-700";
  return <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${color}`}>{status}</span>;
}
