import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { adminApi, asList, chatApi } from "../api/client";
import { hasAnyPermission, roleNames } from "../auth/access";
import { useCurrentUser } from "../auth/CurrentUserContext";
import { untrustedText } from "../security/untrusted";

type Citation = {
  document_id?: string;
  document_name?: string;
  page?: number;
  chunk_id?: string;
  section?: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
};

type Conversation = {
  id: string;
  title?: string | null;
  updated_at?: string | null;
};

const CONV_KEY = "active_conversation_id";

export default function ChatPage() {
  const user = useCurrentUser();
  const navigate = useNavigate();
  const canDelete = hasAnyPermission(user, ["conversation:delete"]);
  const [question, setQuestion] = useState(() => new URLSearchParams(window.location.search).get("q") || "");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("fresh") === "1") {
      localStorage.removeItem(CONV_KEY);
      return undefined;
    }
    const fromUrl = params.get("c");
    if (fromUrl) {
      localStorage.setItem(CONV_KEY, fromUrl);
      return fromUrl;
    }
    return localStorage.getItem(CONV_KEY) || undefined;
  });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [ollamaDown, setOllamaDown] = useState(false);
  const [feedbackSaved, setFeedbackSaved] = useState<Record<string, string>>({});
  const [feedbackError, setFeedbackError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef(false);

  async function refreshConversations() {
    const rows = asList<Conversation>(await chatApi.conversations());
    setConversations(rows);
  }

  async function loadConversation(id: string) {
    const rows = asList<ChatMessage>(await chatApi.messages(id));
    setMessages(
      rows.map((m: ChatMessage) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        citations: m.citations || [],
      })),
    );
    setConversationId(id);
    localStorage.setItem(CONV_KEY, id);
  }

  useEffect(() => {
    chatApi
      .conversations()
      .then((data) => {
        const rows = asList<Conversation>(data);
        setConversations(rows);
        if (new URLSearchParams(window.location.search).get("fresh") === "1") return;
        const stored = localStorage.getItem(CONV_KEY);
        if (stored && rows.some((c) => c.id === stored)) {
          setConversationId(stored);
        } else if (rows[0]) {
          setConversationId(rows[0].id);
        }
      })
      .catch(() => undefined);
    adminApi
      .health()
      .then((h: { ollama?: { reachable?: boolean } }) => setOllamaDown(h?.ollama?.reachable === false))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!conversationId || pendingRef.current) return;
    loadConversation(conversationId).catch(() => {
      localStorage.removeItem(CONV_KEY);
      setConversationId(undefined);
      setMessages([]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  function startNew() {
    localStorage.removeItem(CONV_KEY);
    setConversationId(undefined);
    setMessages([]);
    setQuestion("");
    setError("");
  }

  async function deleteConversation(id: string) {
    setError("");
    try {
      await chatApi.deleteConversation(id);
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);
      if (conversationId === id) {
        localStorage.removeItem(CONV_KEY);
        setConversationId(remaining[0]?.id);
        if (!remaining[0]) setMessages([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete conversation");
    }
  }

  async function clearAllConversations() {
    if (conversations.length === 0) return;
    if (!window.confirm("Delete all conversations? This cannot be undone.")) return;
    setError("");
    try {
      await chatApi.deleteAllConversations();
      localStorage.removeItem(CONV_KEY);
      setConversations([]);
      setConversationId(undefined);
      setMessages([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clear conversations");
    }
  }

  async function send(text: string) {
    if (!text || pending) return;
    setError("");
    setPending(true);
    pendingRef.current = true;
    setQuestion("");
    if (window.location.search) navigate({ pathname: "/", search: "" }, { replace: true });
    const tempId = `local-${Date.now()}`;
    setMessages((prev) => [...prev, { id: tempId, role: "user", content: text }]);
    const streamId = `stream-${Date.now()}`;
    setMessages((prev) => [...prev, { id: streamId, role: "assistant", content: "" }]);
    try {
      let completed = false;
      let assembled = "";
      await chatApi.streamAsk(text, conversationId, (event) => {
        if (event.event === "token" && event.token) {
          assembled += event.token;
          setMessages((prev) =>
            prev.map((m) => (m.id === streamId ? { ...m, content: m.content + event.token } : m)),
          );
        }
        if (event.event === "citations" && event.citations) {
          setMessages((prev) =>
            prev.map((m) => (m.id === streamId ? { ...m, citations: event.citations as Citation[] } : m)),
          );
        }
        if (event.event === "generation.completed") {
          completed = true;
          const nextId = event.conversation_id as string;
          setConversationId(nextId);
          localStorage.setItem(CONV_KEY, nextId);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === streamId
                ? {
                    ...m,
                    id: (event.message_id as string) || m.id,
                    citations: (event.citations as Citation[]) || m.citations,
                  }
                : m,
            ),
          );
        }
        if (event.event === "error") {
          setError(event.message || "Generation failed");
        }
      });
      if (!completed && !assembled) {
        const result = await chatApi.ask(text, conversationId);
        const nextId = result.conversation_id as string;
        setConversationId(nextId);
        localStorage.setItem(CONV_KEY, nextId);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamId
              ? {
                  id: result.message_id,
                  role: "assistant",
                  content: result.answer,
                  citations: result.citations || [],
                }
              : m,
          ),
        );
      }
      await refreshConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
      setMessages((prev) => prev.filter((m) => m.id !== streamId || Boolean(m.content)));
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(question.trim());
  }

  async function rate(messageId: string, rating: "up" | "down") {
    setFeedbackError("");
    try {
      await chatApi.feedback(messageId, rating);
      setFeedbackSaved((prev) => ({ ...prev, [messageId]: rating }));
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : "Could not save feedback. Try again.");
    }
  }

  const prompts = [
    { label: "What can I ask about?", text: "Which documents am I allowed to ask questions about?" },
    { label: "Summarize what I can read", text: "Summarize the documents I am allowed to read." },
  ];

  const active = conversations.find((c) => c.id === conversationId);
  const role = roleNames(user)[0];

  return (
    <section className="flex min-h-[calc(100vh-8.5rem)] flex-1 flex-col overflow-hidden rounded-xl bg-surface-lowest shadow-card md:flex-row">
      <aside className="flex max-h-48 w-full shrink-0 flex-col bg-surface-lowest md:max-h-none md:w-64">
        <div className="flex h-14 items-center justify-between bg-surface-low/40 px-4">
          <h1 className="text-headline-sm">Conversations</h1>
          <div className="flex items-center gap-1">
            {canDelete && conversations.length > 0 && (
              <button className="btn btn-ghost h-7 px-2 text-label-sm" type="button" onClick={clearAllConversations}>
                Clear
              </button>
            )}
            <button
              className="inline-flex items-center gap-1 rounded bg-surface-container px-2.5 py-1 text-label-sm text-on-surface hover:bg-surface-high"
              type="button"
              onClick={startNew}
            >
              + New
            </button>
          </div>
        </div>
        <ul className="flex-1 space-y-1 overflow-y-auto p-3 text-body-md">
          {conversations.map((c) => (
            <li key={c.id} className="group relative flex items-center gap-1">
              {c.id === conversationId && (
                <span className="absolute bottom-1.5 left-0 top-1.5 w-1 rounded-r bg-primary" />
              )}
              <button
                type="button"
                onClick={() => loadConversation(c.id)}
                className={`min-w-0 flex-1 truncate rounded-lg px-3 py-2.5 pl-3 text-left ${
                  c.id === conversationId
                    ? "bg-surface-low font-medium text-on-surface"
                    : "text-on-variant hover:bg-surface-low hover:text-on-surface"
                }`}
              >
                {untrustedText(c.title || "Untitled")}
              </button>
              {canDelete && (
              <button
                type="button"
                aria-label={`Delete ${untrustedText(c.title || "conversation")}`}
                title="Delete"
                className="shrink-0 rounded-md p-1.5 text-on-variant hover:bg-error-container/40 hover:text-on-error-container md:opacity-0 md:group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation();
                  deleteConversation(c.id);
                }}
              >
                <TrashIcon />
              </button>
              )}
            </li>
          ))}
          {conversations.length === 0 && (
            <li className="px-3 py-4 text-body-sm text-on-variant">No threads yet. Ask a question to start one.</li>
          )}
        </ul>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col bg-surface-low">
        <div className="flex h-14 items-center justify-between bg-surface-lowest px-6 shadow-sm">
          <div className="min-w-0">
            <h2 className="truncate text-headline-sm">{untrustedText(active?.title || "New conversation")}</h2>
            <p className="text-label-sm text-secondary">
              {role ? `${role}. ` : ""}Answers use only documents you are allowed to read.
            </p>
            {ollamaDown && (
              <p className="mt-0.5 text-body-sm text-error">
                Ollama is not running, so a new answer cannot be generated. Start it with `ollama serve`. Saved
                conversations on the left still open.
              </p>
            )}
          </div>
          {conversationId && canDelete && (
            <button
              className="inline-flex h-8 w-8 items-center justify-center rounded text-secondary hover:bg-surface-container"
              type="button"
              aria-label="Delete chat"
              title="Delete chat"
              onClick={() => deleteConversation(conversationId)}
            >
              <TrashIcon />
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {messages.length === 0 && !pending && (
            <div className="mx-auto mt-10 max-w-lg text-center">
              <p className="text-headline-md text-on-surface">Ask about documents you can read</p>
              <p className="mt-2 text-body-md text-on-variant">
                Follow-ups stay in this thread. Start a new chat from the left for a fresh context.
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {prompts.map((prompt) => (
                  <button
                    key={prompt.label}
                    className="btn btn-secondary"
                    type="button"
                    disabled={pending}
                    onClick={() => send(prompt.text)}
                  >
                    {prompt.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                savedRating={feedbackSaved[m.id]}
                onRate={rate}
              />
            ))}
            {pending && !(messages.at(-1)?.role === "assistant" && messages.at(-1)?.content) && (
              <div className="max-w-[92%] rounded-2xl rounded-tl-sm bg-surface-lowest px-5 py-4 text-body-lg text-on-variant shadow-sm">
                Searching documents and writing an answer…
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
        {error && (
          <p className="px-6 pb-2 text-body-sm text-error">
            {error} Check that the API is running, then ask again.
          </p>
        )}
        {feedbackError && <p className="px-6 pb-2 text-body-sm text-error">{feedbackError}</p>}
        <form className="border-t border-outline-variant/30 bg-surface-lowest p-4" onSubmit={onSubmit}>
          <div className="mx-auto flex max-w-3xl gap-2">
            <input
              className="h-11 flex-1 rounded-xl border border-outline-variant/70 bg-surface-lowest px-4 text-body-md outline-none focus:ring-1 focus:ring-primary"
              placeholder={conversationId ? "Ask a follow-up about your documents…" : "Ask about your documents"}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button className="btn btn-primary h-11 rounded-xl px-4" type="submit" disabled={pending || !question.trim()}>
              {pending ? "Asking…" : "Ask"}
            </button>
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-label-sm text-on-variant">
            Press Enter to submit. Citations are only shown for retrieved chunks.
          </p>
        </form>
      </div>
    </section>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M4 7h16" strokeLinecap="round" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" strokeLinecap="round" />
      <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 11v6M14 11v6" strokeLinecap="round" />
    </svg>
  );
}

function MessageBubble({
  message,
  savedRating,
  onRate,
}: {
  message: ChatMessage;
  savedRating?: string;
  onRate: (id: string, rating: "up" | "down") => void;
}) {
  const mine = message.role === "user";
  const canRate = !mine && message.id && !message.id.startsWith("local-") && !message.id.startsWith("stream-");
  return (
    <div className={`flex flex-col ${mine ? "items-end" : "items-start"}`}>
      {!mine && (
        <div className="mb-1.5 flex items-center gap-2">
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-on-primary">
            R
          </span>
          <span className="text-label-sm font-semibold text-on-surface">RAG Assistant</span>
        </div>
      )}
      <div
        className={
          mine
            ? "max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-5 py-3.5 text-body-lg leading-relaxed text-on-primary"
            : "max-w-[92%] space-y-3.5 rounded-2xl rounded-tl-sm bg-surface-lowest p-5 text-on-surface shadow-sm"
        }
      >
        {mine ? <p>{untrustedText(message.content)}</p> : <AnswerBody text={untrustedText(message.content, 20000)} />}
        {!mine && message.citations && message.citations.length > 0 && (
          <div className="rounded-lg bg-surface-low/60 p-3">
            <p className="text-label-sm font-semibold uppercase tracking-wider text-secondary">
              Sources you can read ({message.citations.length})
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {message.citations.map((c, i) => (
                <li
                  key={c.chunk_id || i}
                  className="flex flex-wrap items-center justify-between gap-2 rounded bg-surface-lowest px-2.5 py-1.5 text-body-sm text-on-surface shadow-sm"
                >
                  <span>
                    <span className="font-medium">
                      [{i + 1}] {untrustedText(c.document_name)}
                    </span>
                    {c.page != null ? <span className="text-secondary"> · p. {c.page}</span> : null}
                    {c.section ? <span className="text-secondary"> · {untrustedText(c.section)}</span> : null}
                  </span>
                  {c.document_id && (
                    <Link className="link-action" to={`/documents?focus=${encodeURIComponent(c.document_id)}`}>
                      Open source
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!mine && message.content && (!message.citations || message.citations.length === 0) && (
          <p className="text-body-sm text-on-variant">No document you can read was cited for this answer.</p>
        )}
        {canRate && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              className={`btn h-8 ${savedRating === "up" ? "btn-primary" : "btn-secondary"}`}
              type="button"
              onClick={() => onRate(message.id, "up")}
            >
              Helpful
            </button>
            <button
              className={`btn h-8 ${savedRating === "down" ? "btn-primary" : "btn-ghost"}`}
              type="button"
              onClick={() => onRate(message.id, "down")}
            >
              Not helpful
            </button>
            {savedRating && <span className="text-body-sm text-on-variant">Saved with this answer.</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function AnswerBody({ text }: { text: string }) {
  const blocks = tidyText(text)
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const isList = lines.every((ln) => /^[-*]\s+/.test(ln.trim()) || ln.trim() === "");
        if (isList) {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.filter((ln) => ln.trim()).map((ln, j) => (
                <li key={j}>{renderRich(ln.replace(/^[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        }
        const heading = block.match(/^\*\*(.+?)\*\*\s*$/);
        if (heading) {
          return (
            <p key={i} className="font-semibold">
              {heading[1]}
            </p>
          );
        }
        return <p key={i}>{renderRich(block)}</p>;
      })}
    </div>
  );
}

function tidyText(text: string): string {
  const normalized = text.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n");
  if (/\*\*|^\s*[-*]\s/m.test(normalized)) {
    return normalized;
  }
  const lines = normalized.split("\n");
  const merged: string[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      if (merged.at(-1) !== "") merged.push("");
      continue;
    }
    const prev = merged.at(-1);
    if (prev && prev !== "" && prev.length < 72 && !/[.!?]$/.test(prev) && !/^sources$/i.test(line)) {
      merged[merged.length - 1] = `${prev} ${line}`;
    } else {
      merged.push(line);
    }
  }
  return merged.join("\n").replace(/\n{3,}/g, "\n\n");
}

function renderRich(text: string) {
  const chunks = text.split(/(\*\*[^*]+\*\*|\[\d+\])/g).filter(Boolean);
  return chunks.map((part, i) => {
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      return (
        <sup key={i} className="mx-0.5 rounded bg-surface-container px-1 font-semibold text-on-surface">
          {cite[1]}
        </sup>
      );
    }
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) {
      return (
        <strong key={i} className="font-semibold">
          {bold[1]}
        </strong>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
