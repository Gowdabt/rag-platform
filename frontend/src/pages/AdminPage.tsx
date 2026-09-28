import { FormEvent, useEffect, useState } from "react";
import { adminApi, evalApi, sourcesApi } from "../api/client";

export default function AdminPage() {
  const [stats, setStats] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<Array<{ id: string; status: string; error?: string }>>([]);
  const [usage, setUsage] = useState<{ events?: number; input_tokens?: number; output_tokens?: number } | null>(null);
  const [audit, setAudit] = useState<Array<{ id: string; action: string; created_at?: string }>>([]);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [datasets, setDatasets] = useState<Array<{ id: string; name: string }>>([]);
  const [evalName, setEvalName] = useState("smoke-eval");
  const [question, setQuestion] = useState("");
  const [expected, setExpected] = useState("");
  const [evalResult, setEvalResult] = useState<string>("");
  const [health, setHealth] = useState<{
    status?: string;
    ollama?: { reachable?: boolean; llm_model_present?: boolean; embedding_model_present?: boolean; base?: string };
    providers?: { llm_model?: string; embedding_model?: string };
  } | null>(null);
  const [reindexMsg, setReindexMsg] = useState("");
  const [runtimeMsg, setRuntimeMsg] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [temperature, setTemperature] = useState("0.1");
  const [chunkSize, setChunkSize] = useState("800");
  const [chunkOverlap, setChunkOverlap] = useState("120");
  const [fsRoots, setFsRoots] = useState("");
  const [googleId, setGoogleId] = useState("");
  const [googleSecret, setGoogleSecret] = useState("");
  const [msId, setMsId] = useState("");
  const [msSecret, setMsSecret] = useState("");
  const [dbxId, setDbxId] = useState("");
  const [dbxSecret, setDbxSecret] = useState("");

  async function refresh() {
    const [s, j, c, u, a, d, h] = await Promise.all([
      adminApi.stats(),
      adminApi.jobs(),
      adminApi.config(),
      adminApi.usage().catch(() => null),
      adminApi.audit().catch(() => []),
      evalApi.datasets().catch(() => []),
      adminApi.health().catch(() => null),
    ]);
    setStats(s);
    setJobs(j);
    setConfig(c);
    const llm = (c?.llm || {}) as { model?: string; temperature?: number };
    const chunking = (c?.chunking || {}) as { chunk_size?: number; chunk_overlap?: number };
    const connectors = (c?.connectors || {}) as { fs_roots?: string[] };
    setLlmModel(llm.model || "");
    setTemperature(String(llm.temperature ?? 0.1));
    setChunkSize(String(chunking.chunk_size ?? 800));
    setChunkOverlap(String(chunking.chunk_overlap ?? 120));
    setFsRoots((connectors.fs_roots || []).join(", "));
    setUsage(u);
    setAudit(a);
    setDatasets(d);
    setHealth(h);
  }

  useEffect(() => {
    refresh().catch(() => undefined);
  }, []);

  async function onCreateDataset(e: FormEvent) {
    e.preventDefault();
    await evalApi.createDataset(evalName);
    await refresh();
  }

  async function onAddItem(datasetId: string) {
    if (!question) return;
    await evalApi.addItem(datasetId, question, expected || undefined);
    setQuestion("");
    setExpected("");
    setEvalResult("Item added");
  }

  async function onSaveRuntime(e: FormEvent) {
    e.preventDefault();
    setRuntimeMsg("Saving…");
    try {
      await adminApi.putConfig({
        llm: { model: llmModel, temperature: Number(temperature) },
        chunking: { chunk_size: Number(chunkSize), chunk_overlap: Number(chunkOverlap) },
        connectors: {
          fs_roots: fsRoots
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean),
        },
      });
      const oauth: Record<string, { client_id: string; client_secret: string }> = {};
      if (googleId.trim() && googleSecret.trim()) oauth.google = { client_id: googleId.trim(), client_secret: googleSecret.trim() };
      if (msId.trim() && msSecret.trim()) oauth.microsoft = { client_id: msId.trim(), client_secret: msSecret.trim() };
      if (dbxId.trim() && dbxSecret.trim()) oauth.dropbox = { client_id: dbxId.trim(), client_secret: dbxSecret.trim() };
      if (Object.keys(oauth).length) await sourcesApi.saveOauthClients(oauth);
      setGoogleSecret("");
      setMsSecret("");
      setDbxSecret("");
      setRuntimeMsg("Saved. No restart required. Drive login uses these values immediately.");
      await refresh();
    } catch (err) {
      setRuntimeMsg(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function onReindex() {
    setReindexMsg("Re-embedding documents with Ollama…");
    try {
      const result = await adminApi.reindex();
      setReindexMsg(
        `Reindexed ${result.documents_embedded ?? 0} documents with ${result.provider}/${result.model}` +
          (result.failed ? ` (${result.failed} failed)` : ""),
      );
    } catch (err) {
      setReindexMsg(err instanceof Error ? err.message : "Reindex failed");
    }
  }

  async function onRun(datasetId: string) {
    const result = await evalApi.run(datasetId);
    setEvalResult(JSON.stringify(result, null, 2));
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="page-title">System</h1>
        <p className="page-sub">Runtime inspection for this tenant: jobs, usage, eval, and config.</p>
      </div>
      {health && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            health.ollama?.reachable
              ? "border-outline-variant/50 bg-surface-lowest"
              : "border-error-container bg-error-container/40 text-on-error-container"
          }`}
        >
          {health.ollama?.reachable ? (
            <span>
              Ollama at {health.ollama.base}: {health.providers?.llm_model}
              {health.ollama.llm_model_present ? " ready" : " model missing"} · embeddings{" "}
              {health.providers?.embedding_model}
              {health.ollama.embedding_model_present ? " ready" : " model missing"}
            </span>
          ) : (
            <span>
              Ollama is not running at {health.ollama?.base || "http://127.0.0.1:11434"}. Start it with `ollama serve`.
            </span>
          )}
          <button className="btn btn-primary ml-3 h-8" type="button" onClick={onReindex}>
            Reindex embeddings
          </button>
          {reindexMsg && <div className="mt-2 text-[12px]">{reindexMsg}</div>}
        </div>
      )}
      <div className="grid grid-cols-3 gap-4">
        <Stat label="Documents" value={stats.documents} />
        <Stat label="Jobs" value={stats.jobs} />
        <Stat label="Failed jobs" value={stats.failed_jobs} warn />
      </div>
      <form className="panel p-4" onSubmit={onSaveRuntime}>
        <h2 className="text-[15px] font-semibold">Runtime settings</h2>
        <p className="mt-1 text-[13px] text-on-variant">
          Saved for this tenant without restarting. Drive/OneDrive/Dropbox client secrets are encrypted. Leave secret fields blank to keep the current value.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            LLM model
            <input className="input-field mt-1" value={llmModel} onChange={(e) => setLlmModel(e.target.value)} />
          </label>
          <label className="text-sm">
            Temperature
            <input className="input-field mt-1" value={temperature} onChange={(e) => setTemperature(e.target.value)} />
          </label>
          <label className="text-sm">
            Chunk size
            <input className="input-field mt-1" value={chunkSize} onChange={(e) => setChunkSize(e.target.value)} />
          </label>
          <label className="text-sm">
            Chunk overlap
            <input className="input-field mt-1" value={chunkOverlap} onChange={(e) => setChunkOverlap(e.target.value)} />
          </label>
          <label className="text-sm md:col-span-2">
            Local folder allow-list (comma-separated)
            <input className="input-field mt-1" value={fsRoots} onChange={(e) => setFsRoots(e.target.value)} placeholder="Documents, Desktop, ./data/sources" />
            <span className="mt-1 block text-[12px] text-on-variant">
              The Sources folder picker lists these locations. Leave empty to use Documents, Desktop, and project data/sources.
            </span>
          </label>
          <label className="text-sm">
            Google client ID
            <input className="input-field mt-1" value={googleId} onChange={(e) => setGoogleId(e.target.value)} autoComplete="off" />
          </label>
          <label className="text-sm">
            Google client secret
            <input className="input-field mt-1" type="password" value={googleSecret} onChange={(e) => setGoogleSecret(e.target.value)} autoComplete="off" />
          </label>
          <label className="text-sm">
            Microsoft client ID
            <input className="input-field mt-1" value={msId} onChange={(e) => setMsId(e.target.value)} autoComplete="off" />
          </label>
          <label className="text-sm">
            Microsoft client secret
            <input className="input-field mt-1" type="password" value={msSecret} onChange={(e) => setMsSecret(e.target.value)} autoComplete="off" />
          </label>
          <label className="text-sm">
            Dropbox client ID
            <input className="input-field mt-1" value={dbxId} onChange={(e) => setDbxId(e.target.value)} autoComplete="off" />
          </label>
          <label className="text-sm">
            Dropbox client secret
            <input className="input-field mt-1" type="password" value={dbxSecret} onChange={(e) => setDbxSecret(e.target.value)} autoComplete="off" />
          </label>
        </div>
        <button className="btn btn-primary mt-3" type="submit">
          Save runtime settings
        </button>
        {runtimeMsg && <p className="mt-2 text-sm text-on-variant">{runtimeMsg}</p>}
      </form>
      {usage && (
        <p className="text-sm text-on-variant">
          Usage: {usage.events ?? 0} events, {usage.input_tokens ?? 0} in / {usage.output_tokens ?? 0} out tokens
        </p>
      )}
      <div className="panel p-4">
        <h2 className="text-[15px] font-semibold">Recent jobs</h2>
        <ul className="mt-3 text-sm">
          {jobs.map((j) => (
            <li key={j.id} className="flex items-center justify-between border-b border-outline-variant/30 py-2 last:border-0">
              <span className="font-mono text-[12px] text-on-variant">{j.id.slice(0, 8)}</span>
              <span>{j.status}{j.error ? ` — ${j.error}` : ""}</span>
            </li>
          ))}
          {jobs.length === 0 && <li className="py-2 text-on-variant">No jobs yet</li>}
        </ul>
      </div>
      <div className="panel p-4">
        <h2 className="text-[15px] font-semibold">Evaluation</h2>
        <form className="mt-3 flex gap-2" onSubmit={onCreateDataset}>
          <input className="h-9 rounded-lg border border-outline-variant/70 px-3 text-[13px]" value={evalName} onChange={(e) => setEvalName(e.target.value)} />
          <button className="btn btn-primary" type="submit">
            New dataset
          </button>
        </form>
        {datasets.map((d) => (
          <div key={d.id} className="mt-3 rounded-lg bg-surface-low p-3 text-sm">
            <div className="font-medium">{d.name}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <input className="h-8 rounded-lg border border-outline-variant/70 px-2" placeholder="Question" value={question} onChange={(e) => setQuestion(e.target.value)} />
              <input className="h-8 rounded-lg border border-outline-variant/70 px-2" placeholder="Expected answer" value={expected} onChange={(e) => setExpected(e.target.value)} />
              <button className="rounded-lg border border-outline-variant px-2 py-1" type="button" onClick={() => onAddItem(d.id)}>
                Add item
              </button>
              <button className="btn btn-primary h-8" type="button" onClick={() => onRun(d.id)}>
                Run
              </button>
            </div>
          </div>
        ))}
        {evalResult && <pre className="mt-3 overflow-auto rounded-lg bg-primary-container p-3 font-mono text-[11px] text-surface-highest">{evalResult}</pre>}
      </div>
      <div className="panel p-4">
        <h2 className="text-[15px] font-semibold">Audit</h2>
        <ul className="mt-2 text-sm">
          {audit.slice(0, 20).map((a) => (
            <li key={a.id} className="border-b border-outline-variant/30 py-2 last:border-0">
              {a.action} {a.created_at ? `— ${a.created_at}` : ""}
            </li>
          ))}
          {audit.length === 0 && <li className="py-2 text-on-variant">No audit events yet</li>}
        </ul>
      </div>
      {config && (
        <div className="overflow-hidden rounded-xl border border-outline-variant/50 bg-primary-container p-4 shadow-card">
          <h2 className="text-[13px] font-medium text-surface-highest">Configuration</h2>
          <pre className="mt-2 overflow-auto font-mono text-[11px] text-surface-high">
            {JSON.stringify(config, null, 2)}
          </pre>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value, warn }: { label: string; value?: number; warn?: boolean }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${warn && value ? "text-error" : ""}`}>{value ?? 0}</div>
    </div>
  );
}
