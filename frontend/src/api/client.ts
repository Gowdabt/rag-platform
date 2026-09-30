function resolveApiBase(): string {
  const configured = (import.meta.env.VITE_API_URL ?? "").trim().replace(/\/$/, "");
  if (configured) return configured;
  if (import.meta.env.DEV) {
    // Literal 127.0.0.1 matches uvicorn --host 127.0.0.1. `localhost` can resolve
    // to IPv6 ::1 on macOS and fail with TypeError "Failed to fetch".
    return "http://127.0.0.1:8000";
  }
  // Production / Electron: same-origin (FastAPI SPA on :8000 or :17800).
  return "";
}

export const apiBase = resolveApiBase();

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function unreachableMessage(): string {
  const target = apiBase || window.location.origin;
  return `Cannot reach the API at ${target}. Confirm the backend is running (http://127.0.0.1:8000) and try again.`;
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(`${apiBase}${path}`, init);
  } catch {
    throw new ApiError(unreachableMessage(), 0);
  }
}

function token() {
  return localStorage.getItem("access_token");
}

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const rec = body as { detail?: unknown; title?: string; message?: string; errors?: unknown };
  const detail = rec.detail;
  if (typeof detail === "string" && detail.trim() && detail.trim() !== "Request validation failed") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) return String((item as { msg: string }).msg);
      return "";
    });
    const joined = parts.filter(Boolean).join("; ");
    if (joined) return joined;
  }
  if (Array.isArray(rec.errors)) {
    const parts = rec.errors.map((item) => {
      if (!item || typeof item !== "object") return "";
      const err = item as { loc?: unknown; msg?: string };
      const loc = Array.isArray(err.loc) ? err.loc.filter((p) => p !== "body" && p !== "query").join(".") : "";
      const msg = typeof err.msg === "string" ? err.msg : "";
      if (loc && msg) return `${loc}: ${msg}`;
      return msg;
    });
    const joined = parts.filter(Boolean).join("; ");
    if (joined) return joined;
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  if (typeof rec.title === "string" && rec.title.trim()) return rec.title;
  if (typeof rec.message === "string" && rec.message.trim()) return rec.message;
  return fallback;
}

export async function api(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await apiFetch(path, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(errorMessage(body, res.statusText), res.status);
  }
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Normalize list payloads whether the API returns an array or `{items|results|data: []}`. */
export function asList<T = unknown>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object") {
    const o = data as Record<string, unknown>;
    for (const key of [
      "items",
      "results",
      "data",
      "tenants",
      "users",
      "roles",
      "folders",
      "permissions",
      "grants",
      "models",
      "allowed_models",
      "events",
      "logs",
      "catalog",
    ]) {
      if (Array.isArray(o[key])) return o[key] as T[];
    }
  }
  return [];
}

export async function apiOptional(path: string, init: RequestInit = {}) {
  try {
    return await api(path, init);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 405)) return null;
    throw err;
  }
}

function normalizeTenantSlug(slug?: string): string {
  return (slug || "").trim().toLowerCase();
}

export const auth = {
  signup: (email: string, password: string, tenant_name: string) =>
    api("/api/v1/auth/signup", { method: "POST", body: JSON.stringify({ email, password, tenant_name }) }),
  login: (email: string, password: string, tenant_slug?: string) => {
    const slug = normalizeTenantSlug(tenant_slug);
    return api("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        ...(slug ? { tenant_slug: slug } : {}),
      }),
    });
  },
  logout: (refresh_token: string) =>
    api("/api/v1/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token }) }),
  me: () => api("/api/v1/auth/me"),
  features: () => api("/api/v1/auth/features"),
  forgotPassword: (tenant_slug: string, email: string) =>
    api("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ tenant_slug: normalizeTenantSlug(tenant_slug), email }),
    }),
  resetPassword: (token: string, password: string) =>
    api("/api/v1/auth/reset-password", { method: "POST", body: JSON.stringify({ token, password }) }),
  acceptInvite: (token: string, password: string) =>
    api("/api/v1/auth/accept-invite", { method: "POST", body: JSON.stringify({ token, password }) }),
};

export const docs = {
  list: () => api("/api/v1/documents"),
  versions: (id: string) => api(`/api/v1/documents/${id}/versions`),
  share: (id: string, body: Record<string, unknown>) =>
    api(`/api/v1/documents/${id}/acl`, { method: "POST", body: JSON.stringify(body) }),
  upload: async (file: File, workspaceId?: string) => {
    const body = new FormData();
    body.append("file", file);
    if (workspaceId) body.append("workspace_id", workspaceId);
    return api("/api/v1/documents", { method: "POST", body });
  },
};

export type ChatStreamEvent = {
  event: string;
  token?: string;
  citations?: unknown[];
  conversation_id?: string;
  message_id?: string;
  message?: string;
  chunk_count?: number;
};

export const chatApi = {
  ask: (question: string, conversation_id?: string, workspace_id?: string) =>
    api("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify({ question, conversation_id, workspace_id }),
    }),
  streamAsk: async (
    question: string,
    conversation_id: string | undefined,
    onEvent: (event: ChatStreamEvent) => void,
  ) => {
    const headers = new Headers();
    headers.set("Accept", "text/event-stream");
    headers.set("Content-Type", "application/json");
    const t = token();
    if (t) headers.set("Authorization", `Bearer ${t}`);
    const res = await apiFetch("/api/v1/chat/stream", {
      method: "POST",
      headers,
      body: JSON.stringify({ question, conversation_id }),
    });
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.title || res.statusText);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as ChatStreamEvent);
        } catch {
          /* ignore malformed frames */
        }
      }
    }
  },
  conversations: () => api("/api/v1/conversations"),
  messages: (id: string) => api(`/api/v1/conversations/${id}`),
  deleteConversation: (id: string) => api(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  deleteAllConversations: () => api("/api/v1/conversations", { method: "DELETE" }),
  feedback: (messageId: string, rating: string) =>
    api(`/api/v1/messages/${messageId}/feedback`, { method: "POST", body: JSON.stringify({ rating }) }),
};

export const adminApi = {
  stats: () => api("/api/v1/admin/stats"),
  jobs: () => api("/api/v1/jobs"),
  audit: () => api("/api/v1/audit-logs"),
  usage: () => api("/api/v1/usage"),
  config: () => api("/api/v1/config"),
  putConfig: (payload: Record<string, unknown>) =>
    api("/api/v1/config", { method: "PUT", body: JSON.stringify({ payload }) }),
  health: () => api("/api/v1/health"),
  reindex: () => api("/api/v1/admin/reindex", { method: "POST" }),
  users: () => api("/api/v1/users"),
  teams: () => api("/api/v1/teams"),
};

export const sourcesApi = {
  catalog: () => api("/api/v1/connectors/catalog"),
  list: () => api("/api/v1/connectors"),
  oauthClients: () => api("/api/v1/connectors/oauth/clients"),
  saveOauthClients: (body: Record<string, { client_id: string; client_secret: string }>) =>
    api("/api/v1/connectors/oauth/clients", { method: "PUT", body: JSON.stringify(body) }),
  create: (connector_type: string, name?: string, connector_config?: Record<string, string>) =>
    api("/api/v1/connectors", { method: "POST", body: JSON.stringify({ connector_type, name, connector_config }) }),
  oauthStart: (connector_type: string, sourceId?: string) =>
    api("/api/v1/connectors/oauth/start", {
      method: "POST",
      body: JSON.stringify({
        connector_type,
        source_id: sourceId,
        redirect_uri: `${window.location.origin}/sources`,
      }),
    }),
  oauthCallback: (code: string, state: string) =>
    api("/api/v1/connectors/oauth/callback", { method: "POST", body: JSON.stringify({ code, state }) }),
  disconnect: (id: string) => api(`/api/v1/connectors/${id}`, { method: "DELETE" }),
  locations: (id: string, parentId?: string) =>
    api(`/api/v1/connectors/${id}/locations${parentId ? `?parent_id=${encodeURIComponent(parentId)}` : ""}`),
  children: (id: string, locationId: string) =>
    api(`/api/v1/connectors/${id}/locations/${encodeURIComponent(locationId)}/children`),
  resolveLocation: (id: string, url: string) =>
    api(`/api/v1/connectors/${id}/resolve-location`, { method: "POST", body: JSON.stringify({ url }) }),
  browseLocal: (path?: string) =>
    api(`/api/v1/connectors/local-fs/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  subscribe: (
    id: string,
    body: {
      location_id: string;
      location_name: string;
      include_subfolders?: boolean;
      file_filters?: string[];
      schedule?: string;
    },
  ) => api(`/api/v1/connectors/${id}/subscriptions`, { method: "POST", body: JSON.stringify(body) }),
  patchSubscription: (id: string, body: Record<string, unknown>) =>
    api(`/api/v1/subscriptions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  sync: (id: string) => api(`/api/v1/subscriptions/${id}/sync`, { method: "POST" }),
  syncHistory: (id: string) => api(`/api/v1/subscriptions/${id}/sync-history`),
};

export const evalApi = {
  datasets: () => api("/api/v1/eval/datasets"),
  createDataset: (name: string, description?: string) =>
    api("/api/v1/eval/datasets", { method: "POST", body: JSON.stringify({ name, description }) }),
  addItem: (datasetId: string, question: string, expected_answer?: string) =>
    api(`/api/v1/eval/datasets/${datasetId}/items`, {
      method: "POST",
      body: JSON.stringify({ question, expected_answer }),
    }),
  run: (datasetId: string) =>
    api(`/api/v1/eval/datasets/${datasetId}/runs`, { method: "POST", body: JSON.stringify({}) }),
};

function withPage(path: string, limit = 100, offset = 0): string {
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}limit=${limit}&offset=${offset}`;
}

export const platformApi = {
  tenants: () => api(withPage("/api/v1/platform/tenants")),
  getTenant: (id: string) => api(`/api/v1/platform/tenants/${id}`),
  createTenant: (body: {
    name: string;
    slug: string;
    admin_name: string;
    admin_email: string;
    admin_password?: string;
    company_name?: string;
  }) => api("/api/v1/platform/tenants", { method: "POST", body: JSON.stringify(body) }),
  patchTenant: (id: string, body: Record<string, unknown>) =>
    api(`/api/v1/platform/tenants/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  aiCatalog: () => api("/api/v1/platform/ai-catalog"),
  auditLogs: () => api(withPage("/api/v1/platform/audit-logs")),
};

export const foldersApi = {
  list: () => api("/api/v1/folders"),
  create: (body: { name: string; parent_id?: string | null }) =>
    api("/api/v1/folders", { method: "POST", body: JSON.stringify(body) }),
  update: (id: string, body: { name: string }) =>
    api(`/api/v1/folders/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => api(`/api/v1/folders/${id}`, { method: "DELETE" }),
  shares: (id: string) => api(`/api/v1/folders/${id}/share`),
  share: (
    id: string,
    body: {
      subject_type: "user" | "role";
      email?: string;
      role_id?: string;
      actions: string[];
    },
  ) => api(`/api/v1/folders/${id}/share`, { method: "POST", body: JSON.stringify(body) }),
  unshare: (id: string, grantId: string) =>
    api(`/api/v1/folders/${id}/grants/${grantId}`, { method: "DELETE" }),
};

export const rolesApi = {
  list: () => api("/api/v1/roles"),
  permissions: () => api("/api/v1/permissions"),
  create: (body: { name: string; description?: string; permissions: string[] }) =>
    api("/api/v1/roles", { method: "POST", body: JSON.stringify(body) }),
  update: (id: string, body: { name: string; description?: string; permissions: string[] }) =>
    api(`/api/v1/roles/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (id: string) => api(`/api/v1/roles/${id}`, { method: "DELETE" }),
};

export const invitationsApi = {
  create: (body: { name: string; email: string; role_ids?: string[]; role_names?: string[]; roles?: string[] }) =>
    api("/api/v1/users/invitations", {
      method: "POST",
      body: JSON.stringify({
        name: body.name,
        email: body.email,
        role_ids: body.role_ids,
        role_names: body.role_names || body.roles,
      }),
    }),
};

export const usersApi = {
  list: () => api("/api/v1/users"),
  patch: (id: string, body: Record<string, unknown>) =>
    api(`/api/v1/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  resendInvite: (id: string) => api(`/api/v1/users/${id}/resend-invite`, { method: "POST" }),
};

export const aiConfigApi = {
  get: () => api("/api/v1/tenant/ai-config"),
  put: (body: Record<string, unknown>) =>
    api("/api/v1/tenant/ai-config", { method: "PUT", body: JSON.stringify(body) }),
};
