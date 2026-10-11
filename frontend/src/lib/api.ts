/** Typed client for the API. The contract is `docs/api/openapi.json`; types come from `npm run gen:api`. */
import { readSse } from "./sse";
import type {
  AlertOut,
  DemoSummary,
  InvestigationDetail,
  InvestigationSummary,
  Meta,
  Recording,
  RunEvent,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export type ApiErrorKind = "unreachable" | "limit" | "disabled" | "invalid" | "not_found" | "server";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly extra: { retryAfter?: number; limit?: number; remaining?: number } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind =
      status === 0
        ? "unreachable"
        : status === 429
          ? "limit"
          : status === 503
            ? "disabled"
            : status === 404
              ? "not_found"
              : status === 422
                ? "invalid"
                : "server";
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new ApiError(0, "unreachable", "The server could not be reached.");
  }
  if (response.ok) return response;
  let code = "error";
  let message = `The server answered with status ${response.status}.`;
  let extra: ApiError["extra"] = {};
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string; limit?: number; remaining?: number; fields?: Array<{ message?: string }> };
    };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      const field = body.error.fields?.[0]?.message;
      if (response.status === 422 && field) message = `${message} ${field}.`;
      extra = { limit: body.error.limit, remaining: body.error.remaining };
    }
  } catch {
    // Not JSON: keep the generic message.
  }
  const retry = Number(response.headers.get("Retry-After"));
  if (retry > 0) extra = { ...extra, retryAfter: retry };
  throw new ApiError(response.status, code, message, extra);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await send(path, { signal, headers: { Accept: "application/json" } });
  return (await response.json()) as T;
}

export const api = {
  meta: (signal?: AbortSignal) => getJson<Meta>("/api/meta", signal),
  demos: (signal?: AbortSignal) => getJson<DemoSummary[]>("/api/demos", signal),
  demo: (id: string, signal?: AbortSignal) => getJson<Recording>(`/api/demos/${encodeURIComponent(id)}`, signal),
  investigations: (limit = 50, signal?: AbortSignal) =>
    getJson<InvestigationSummary[]>(`/api/investigations?limit=${limit}`, signal),
  investigation: (id: string, signal?: AbortSignal) =>
    getJson<InvestigationDetail>(`/api/investigations/${encodeURIComponent(id)}`, signal),
  alerts: (limit = 50, signal?: AbortSignal) => getJson<AlertOut[]>(`/api/alerts?limit=${limit}`, signal),
};

const EVENT_TYPES = new Set([
  "run_started",
  "scope",
  "llm_call",
  "tool_call",
  "tool_result",
  "note",
  "gate",
  "report",
  "error",
  "run_finished",
]);

/** Accepts only well-formed envelopes of a known type; newer event types are ignored. */
export function parseEvent(text: string): RunEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const e = value as Partial<RunEvent>;
  if (typeof e.seq !== "number" || typeof e.type !== "string" || !EVENT_TYPES.has(e.type)) return null;
  if (!e.data || typeof e.data !== "object") return null;
  return e as RunEvent;
}

async function* events(response: Response): AsyncGenerator<RunEvent> {
  if (!response.body) throw new ApiError(0, "unreachable", "The server sent no stream.");
  try {
    for await (const message of readSse(response.body)) {
      const event = parseEvent(message.data);
      if (event) yield event;
    }
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new ApiError(0, "unreachable", "The connection was lost.");
  }
}

export async function replayDemo(id: string, speed: number, signal: AbortSignal): Promise<AsyncGenerator<RunEvent>> {
  const response = await send(`/api/demos/${encodeURIComponent(id)}/stream?speed=${speed}`, {
    method: "POST",
    signal,
    headers: { Accept: "text/event-stream" },
  });
  return events(response);
}

export async function runLive(question: string, signal: AbortSignal): Promise<AsyncGenerator<RunEvent>> {
  const response = await send("/api/investigations/stream", {
    method: "POST",
    signal,
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return events(response);
}
