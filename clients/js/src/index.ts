/**
 * Lemory TypeScript client — zero-dependency wrapper over the local REST API.
 *
 *   import { Lemory } from "lemory-client";
 *   const mem = new Lemory({ client: "my-agent" });
 *   const hits = await mem.search("결제 모듈 어떻게 하기로 했지?");
 *   await mem.remember("환불은 비동기 큐로 처리하기로 결정", { title: "환불 결정" });
 *
 * Works against `lemory serve` (default http://127.0.0.1:8377). For remote
 * use (mobile/tailnet) pass { baseUrl, token } — the server requires
 * `Authorization: Bearer <api_token>` for non-localhost clients.
 * Uses the global fetch (Node 18+, Bun, Deno, browsers).
 */

export interface LemoryOptions {
  baseUrl?: string;
  /** Shown in the dashboard's per-client usage — identify your agent. */
  client?: string;
  /** api_token from lemory.toml; required for non-localhost access. */
  token?: string;
}

export interface Hit {
  chunk_id: number;
  path: string;
  title: string;
  heading: string;
  text: string;
  score: number;
}

export interface Answer {
  answer: string;
  sources: Hit[];
}

export interface Conflict {
  kind: "number" | "negation" | "duplicate";
  similarity: number;
  detail: string;
  a: { path: string; title: string; text: string };
  b: { path: string; title: string; text: string };
}

export type SearchMode = "hybrid" | "fast" | "vector" | "bm25";

export class LemoryError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "LemoryError";
  }
}

export class Lemory {
  private base: string;
  private headers: Record<string, string>;

  constructor(opts: LemoryOptions = {}) {
    this.base = (opts.baseUrl ?? "http://127.0.0.1:8377").replace(/\/$/, "");
    this.headers = { "X-Lemory-Client": opts.client ?? "js-client" };
    if (opts.token) this.headers["Authorization"] = `Bearer ${opts.token}`;
  }

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(this.base + path, {
      ...init,
      headers: { ...this.headers, "Content-Type": "application/json", ...init?.headers },
    });
    if (!res.ok) throw new LemoryError(res.status, await res.text());
    return res.json() as Promise<T>;
  }

  /** Hybrid retrieval (or mode: "fast" for the no-embedding instant path). */
  search(q: string, opts: { k?: number; mode?: SearchMode } = {}): Promise<Hit[]> {
    const p = new URLSearchParams({ q, k: String(opts.k ?? 8), mode: opts.mode ?? "hybrid" });
    return this.req(`/search?${p}`);
  }

  /** Grounded answer with citations (needs a generator LLM configured). */
  ask(question: string, k = 8): Promise<Answer> {
    return this.req("/ask", { method: "POST", body: JSON.stringify({ question, k }) });
  }

  /** Persist a memory as a Markdown note (duplicate-checked, undoable). */
  remember(
    content: string,
    opts: { title?: string; folder?: string; tags?: string[] } = {},
  ): Promise<{ saved: string; related: unknown[] }> {
    return this.req("/memory", {
      method: "POST",
      body: JSON.stringify({ content, title: opts.title ?? "", folder: opts.folder ?? "memories", tags: opts.tags ?? [] }),
    });
  }

  /** Append-only write to an existing note (creates it if missing). */
  append(path: string, content: string): Promise<{ appended: string }> {
    return this.req("/append", { method: "POST", body: JSON.stringify({ path, content }) });
  }

  /** Undo an AI-written note (refuses human-authored files). */
  trash(path: string): Promise<{ trashed: string; moved_to: string }> {
    return this.req("/memory/trash", { method: "POST", body: JSON.stringify({ path }) });
  }

  /** Cross-note disagreements: number conflicts, negations, duplicates. */
  conflicts(opts: { threshold?: number; limit?: number } = {}): Promise<Conflict[]> {
    const p = new URLSearchParams({
      threshold: String(opts.threshold ?? 0.8),
      limit: String(opts.limit ?? 30),
    });
    return this.req(`/api/conflicts?${p}`);
  }

  /** AI writes awaiting approval (memory_approval mode). */
  pending(): Promise<{ path: string; title: string; mtime: number }[]> {
    return this.req("/api/pending");
  }

  /** Approve a pending AI-written note so it enters the index. */
  approve(path: string): Promise<{ approved: string }> {
    return this.req("/memory/approve", { method: "POST", body: JSON.stringify({ path }) });
  }

  /** Index stats: documents, chunks, links, models, last sync. */
  status(): Promise<Record<string, unknown>> {
    return this.req("/status");
  }

  /** One-call situational context for agent session starts (Zep-style). */
  context(maxChars = 2400): Promise<{ context: string }> {
    return this.req(`/context?max_chars=${maxChars}`);
  }
}
