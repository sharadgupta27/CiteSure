import { answer } from "../test/factories";
import { ApiError, setAuthToken } from "./client";
import { parseSse, streamAsk, type StreamMessage } from "./stream";

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe("parseSse", () => {
  it("parses complete events", () => {
    const { messages, rest } = parseSse(frame("stage", "retrieving") + frame("token", "Hello "));
    expect(messages).toEqual([
      { event: "stage", data: "retrieving" },
      { event: "token", data: "Hello " },
    ]);
    expect(rest).toBe("");
  });

  it("keeps an unfinished event for the next network chunk", () => {
    const first = parseSse('event: token\ndata: "par');
    expect(first.messages).toEqual([]);
    const second = parseSse(first.rest + 'tial"\n\n');
    expect(second.messages).toEqual([{ event: "token", data: "partial" }]);
  });

  it("decodes JSON payloads, including text with newlines and quotes", () => {
    const text = 'line one\nline "two"';
    expect(parseSse(frame("token", text)).messages).toEqual([{ event: "token", data: text }]);
  });

  it("ignores blocks without an event or data", () => {
    expect(parseSse(": keep-alive\n\nevent: stage\n\n" + frame("stage", "ok")).messages).toEqual([{ event: "stage", data: "ok" }]);
  });
});

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

describe("streamAsk", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setAuthToken(null);
  });

  it("sends the token and body, and delivers events even when a network chunk splits one in half", async () => {
    const full = frame("stage", "retrieving") + frame("token", "Hi ") + frame("final", answer());
    const cut = Math.floor(full.length / 2);
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([full.slice(0, cut), full.slice(cut)]));
    vi.stubGlobal("fetch", fetchMock);
    setAuthToken("tok");

    const received: StreamMessage[] = [];
    await streamAsk({ workspace_id: "w1", question: "What?" }, { onMessage: (m) => received.push(m) });

    expect(received.map((m) => m.event)).toEqual(["stage", "token", "final"]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/ask/stream");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(JSON.parse(init.body as string)).toEqual({ workspace_id: "w1", question: "What?" });
  });

  it("throws an ApiError with the server's message for HTTP errors before the stream starts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "not_found", detail: "Workspace not found" }), { status: 404 })),
    );
    await expect(streamAsk({ workspace_id: "w1", question: "What?" }, { onMessage: () => undefined })).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "Workspace not found",
    });
  });

  it("can be aborted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError")));
    const controller = new AbortController();
    controller.abort();
    await expect(streamAsk({ workspace_id: "w", question: "abc" }, { onMessage: () => undefined }, controller.signal)).rejects.toThrow();
    expect(ApiError).toBeDefined();
  });
});
