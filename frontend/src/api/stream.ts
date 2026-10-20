/**
 * Server-Sent Events client for POST /ask/stream. EventSource cannot send a POST body or an Authorization header,
 * so we read the response body ourselves and parse the `event:` / `data:` lines.
 */
import { API_BASE, ApiError, getAuthToken, type Answer, type Schemas } from "./client";

export type StreamMessage =
  | { event: "stage"; data: string }
  | { event: "token"; data: string }
  | { event: "final"; data: Answer }
  | { event: "error"; data: { code: string; detail: string } };

/**
 * Feed text chunks in, get complete events out. A network chunk can end in the middle of an event, so the
 * unfinished tail is kept in `rest` and prepended to the next chunk.
 */
export function parseSse(buffer: string): { messages: StreamMessage[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const messages: StreamMessage[] = [];
  for (const block of parts) {
    let event = "";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (!event || !data) continue;
    messages.push({ event, data: JSON.parse(data) } as StreamMessage);
  }
  return { messages, rest };
}

export interface StreamHandlers {
  onMessage: (message: StreamMessage) => void;
}

export async function streamAsk(body: Schemas["AskRequest"], handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE}/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => ({}))) as { code?: string; detail?: string };
    throw new ApiError(response.status, problem.code ?? "error", problem.detail ?? "Could not start the answer stream");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { messages, rest } = parseSse(buffer);
    buffer = rest;
    messages.forEach(handlers.onMessage);
  }
}
