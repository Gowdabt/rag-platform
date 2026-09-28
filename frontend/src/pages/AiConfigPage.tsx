import { FormEvent, useEffect, useState } from "react";
import { aiConfigApi, ApiError, asList, platformApi } from "../api/client";
import { Alert, PageHeader } from "../components/ui";

type CatalogModel = { id?: string; name?: string; model?: string };

function catalogOptions(data: unknown): string[] {
  if (Array.isArray(data) && data.every((item) => typeof item === "string")) return data as string[];
  return asList<CatalogModel | string>(data)
    .map((row) => {
      if (typeof row === "string") return row;
      return row.model || row.id || row.name || "";
    })
    .filter(Boolean);
}

function readConfig(data: Record<string, unknown> | null) {
  const nested = (data?.llm || {}) as { model?: string; temperature?: number; max_tokens?: number };
  return {
    model: String(data?.model || nested.model || ""),
    temperature: String(data?.temperature ?? nested.temperature ?? 0.1),
    maxTokens: String(data?.max_tokens ?? nested.max_tokens ?? 2048),
    instructions: String(data?.system_instructions || data?.system_prompt || ""),
    rag: Boolean(data?.rag_enabled ?? data?.rag ?? true),
  };
}

export default function AiConfigPage() {
  const [models, setModels] = useState<string[]>([]);
  const [useSelect, setUseSelect] = useState(false);
  const [model, setModel] = useState("");
  const [temperature, setTemperature] = useState("0.1");
  const [maxTokens, setMaxTokens] = useState("2048");
  const [instructions, setInstructions] = useState("");
  const [rag, setRag] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    aiConfigApi
      .get()
      .then((data) => {
        const cfg = readConfig(data || {});
        setModel(cfg.model);
        setTemperature(cfg.temperature);
        setMaxTokens(cfg.maxTokens);
        setInstructions(cfg.instructions);
        setRag(cfg.rag);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load AI configuration"));
    platformApi
      .aiCatalog()
      .then((data) => {
        const options = catalogOptions(data);
        setModels(options);
        setUseSelect(options.length > 0);
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
          setUseSelect(false);
          return;
        }
        setUseSelect(false);
      });
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError("");
    setStatus("Saving…");
    setPending(true);
    try {
      await aiConfigApi.put({
        model,
        temperature: Number(temperature),
        max_tokens: Number(maxTokens),
        system_instructions: instructions,
        rag_enabled: rag,
      });
      setStatus("Saved.");
    } catch (err) {
      setStatus("");
      setError(err instanceof Error ? err.message : "Could not save AI configuration");
    } finally {
      setPending(false);
    }
  }

  const selectOptions = model && !models.includes(model) ? [model, ...models] : models;

  return (
    <section className="space-y-5">
      <PageHeader title="AI Configuration" subtitle="Model must be in the platform allow-list." />
      {error && <Alert>{error}</Alert>}
      <form className="panel p-5" onSubmit={onSave}>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="text-body-md md:col-span-2">
            <span className="field-label">Model</span>
            {useSelect ? (
              <select className="input-field mt-1" value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="">Select a model</option>
                {selectOptions.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="input-field mt-1"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="Current model"
              />
            )}
            <span className="field-help">Model must be in the platform allow-list</span>
          </label>
          <label className="text-body-md">
            <span className="field-label">Temperature</span>
            <input className="input-field mt-1" value={temperature} onChange={(e) => setTemperature(e.target.value)} />
          </label>
          <label className="text-body-md">
            <span className="field-label">Max tokens</span>
            <input className="input-field mt-1" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
          </label>
          <label className="text-body-md md:col-span-2">
            <span className="field-label">System instructions</span>
            <textarea className="textarea-field mt-1" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
          </label>
          <label className="flex items-center gap-2 text-body-md md:col-span-2">
            <input type="checkbox" checked={rag} onChange={(e) => setRag(e.target.checked)} />
            RAG enabled
          </label>
        </div>
        <button className="btn btn-primary mt-4" type="submit" disabled={pending}>
          Save AI configuration
        </button>
        {status && <p className="mt-2 text-body-md text-on-variant">{status}</p>}
      </form>
    </section>
  );
}
