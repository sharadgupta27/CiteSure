import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { getDocumentSpy } from "../test/fakePdfjs";
import { PdfViewer } from "./PdfViewer";

vi.mock("pdfjs-dist", async () => (await import("../test/fakePdfjs")).fakePdfjs);
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/assets/pdf.worker.js" }));

interface Call {
  url: string;
  method: string;
  body: unknown;
}

const annotation = (overrides: Record<string, unknown> = {}) => ({
  id: "a1",
  document_id: "d1",
  page: 2,
  rects: [{ x: 0.1, y: 0.2, w: 0.3, h: 0.02 }],
  text: "16 weeks",
  note: "check this",
  color: "blue",
  created_at: "2026-10-25T10:00:00Z",
  updated_at: "2026-10-25T10:00:00Z",
  ...overrides,
});

let calls: Call[] = [];
let stored: ReturnType<typeof annotation>[] = [];

function stubApi() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : null;
      const url = request ? request.url : String(input);
      const method = (request?.method ?? init?.method ?? "GET").toUpperCase();
      const text = request && method !== "GET" && method !== "DELETE" ? await request.text() : "";
      const body = text ? JSON.parse(text) : null;
      calls.push({ url, method, body });
      const json = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
      const path = new URL(url, "http://localhost").pathname;
      if (path.endsWith("/file")) return new Response(new ArrayBuffer(16), { status: 200 });
      if (path.endsWith("/annotations") && method === "GET") return json(stored);
      if (path.endsWith("/annotations") && method === "POST") {
        const created = annotation({ id: "new1", ...(body as object) });
        stored = [...stored, created];
        return json(created, 201);
      }
      if (path.startsWith("/api/v1/annotations/") && method === "PATCH") {
        stored = stored.map((a) => (a.id === path.split("/").pop() ? { ...a, ...(body as object) } : a));
        return json(stored[0]);
      }
      if (path.startsWith("/api/v1/annotations/") && method === "DELETE") {
        stored = stored.filter((a) => a.id !== path.split("/").pop());
        return new Response(null, { status: 204 });
      }
      return json({ code: "not_found", detail: "no" }, 404);
    }),
  );
}

function renderViewer(props: Partial<{ initialPage: number | null; quote: string }> = {}) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PdfViewer documentId="d1" initialPage={2} quote="16 weeks of fully paid leave" {...props} />
    </QueryClientProvider>,
  );
}

async function ready() {
  return screen.findByRole("region", { name: "PDF pages" });
}

beforeEach(() => {
  stored = [];
  stubApi();
  setAuthToken("tok");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as CanvasRenderingContext2D);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, right: 600, bottom: 800, width: 600, height: 800, x: 0, y: 0, toJSON: () => ({}),
  });
  getDocumentSpy.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("PdfViewer: loading and navigation", () => {
  it("loads the bytes through the authenticated API and opens on the cited page", async () => {
    renderViewer();
    await ready();
    const file = calls.find((c) => c.url.endsWith("/documents/d1/file"));
    expect(file).toBeDefined();
    expect(getDocumentSpy).toHaveBeenCalledTimes(1);
    expect(getDocumentSpy.mock.calls[0]?.[0]).toMatchObject({ isEvalSupported: false, enableXfa: false });
    expect(getDocumentSpy.mock.calls[0]?.[0]).not.toHaveProperty("url");
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByLabelText("Go to page")).toHaveValue(2);
  });

  it("only ever requests same-origin API paths", async () => {
    renderViewer();
    await ready();
    await screen.findByText("Your highlights (0)");
    for (const call of calls) {
      const url = new URL(call.url, window.location.origin);
      expect(url.origin).toBe(window.location.origin);
      expect(url.pathname.startsWith("/api/v1/")).toBe(true);
    }
  });

  it("moves with the previous and next buttons", async () => {
    renderViewer({ initialPage: 1, quote: undefined });
    await ready();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("goes to a typed page number and clamps it", async () => {
    renderViewer({ initialPage: 1, quote: undefined });
    await ready();
    const field = screen.getByLabelText("Go to page");
    await userEvent.clear(field);
    await userEvent.type(field, "3{Enter}");
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "99{Enter}");
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
    expect(field).toHaveValue(3);
  });

  it("supports PageUp, PageDown, Home and End on the focused page region", async () => {
    renderViewer({ initialPage: 1, quote: undefined });
    const region = await ready();
    region.focus();
    await userEvent.keyboard("{PageDown}");
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    await userEvent.keyboard("{End}");
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
    await userEvent.keyboard("{PageUp}");
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    await userEvent.keyboard("{Home}");
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("zooms in and out within limits and resets with Fit", async () => {
    renderViewer();
    await ready();
    const level = screen.getByTestId("zoom-level");
    expect(level).toHaveTextContent("100%");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(level).toHaveTextContent("125%");
    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(level).toHaveTextContent("75%");
    await userEvent.click(screen.getByRole("button", { name: "Fit to width" }));
    expect(level).toHaveTextContent("100%");
    for (let i = 0; i < 4; i++) await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(level).toHaveTextContent("50%");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
  });
});

describe("PdfViewer: the cited quote", () => {
  it("outlines the cited words on the cited page", async () => {
    // jsdom has no layout: Range.getClientRects does not exist, so provide one for this test only
    const proto = Range.prototype as unknown as { getClientRects?: () => unknown[] };
    proto.getClientRects = () => [{ left: 60, top: 100, width: 240, height: 14 }];
    onTestFinished(() => {
      delete proto.getClientRects;
    });
    const { container } = renderViewer();
    await ready();
    await waitFor(() => expect(container.querySelectorAll(".pdf-cited").length).toBeGreaterThan(0));
    const cited = Array.from(container.querySelectorAll(".pdf-cited")).map((el) => el.textContent);
    expect(cited).toEqual(["16 weeks of fully paid leave."]);
    const page2 = container.querySelector('[data-page="2"]') as HTMLElement;
    await waitFor(() => expect(within(page2).getAllByTestId("pdf-cite-rect").length).toBeGreaterThan(0));
    expect(screen.queryByText(/Could not locate the quote/)).not.toBeInTheDocument();
  });

  it("searches all pages when the citation has no page number", async () => {
    const { container } = renderViewer({ initialPage: null });
    await ready();
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    await waitFor(() => expect(container.querySelectorAll(".pdf-cited").length).toBeGreaterThan(0));
  });

  it("jumps to the page and says so when the quote cannot be found", async () => {
    const { container } = renderViewer({ quote: "words that appear nowhere in this document" });
    await ready();
    expect(await screen.findByText("Could not locate the quote on the page; showing the page.")).toBeInTheDocument();
    expect(screen.getByLabelText("Go to page")).toHaveValue(2);
    expect(container.querySelectorAll(".pdf-cited")).toHaveLength(0);
  });
});

describe("PdfViewer: annotations", () => {
  function selectOnPage(container: HTMLElement, page: number, text = "  16 weeks   of fully ") {
    const span = container.querySelector(`[data-page="${page}"] .textLayer span`) as HTMLElement;
    vi.spyOn(window, "getSelection").mockReturnValue({
      isCollapsed: false,
      rangeCount: 1,
      getRangeAt: () => ({
        commonAncestorContainer: span.firstChild,
        getClientRects: () => [{ left: 60, top: 100, width: 300, height: 16 }],
      }),
      toString: () => text,
      removeAllRanges: vi.fn(),
    } as unknown as Selection);
    fireEvent.mouseUp(screen.getByRole("region", { name: "PDF pages" }));
  }

  it("saves a selection as a highlight with colour and note, using normalised rects", async () => {
    const { container } = renderViewer();
    await ready();
    await waitFor(() => expect(container.querySelector('[data-page="2"] .textLayer span')).not.toBeNull());
    selectOnPage(container, 2);
    const group = await screen.findByRole("group", { name: "Save highlight" });
    expect(group).toHaveTextContent("16 weeks of fully");
    await userEvent.click(within(group).getByRole("radio", { name: "green" }));
    await userEvent.type(within(group).getByLabelText("Note (optional)"), "ask HR");
    await userEvent.click(within(group).getByRole("button", { name: "Save highlight" }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toMatch(/\/documents\/d1\/annotations$/);
    expect(post?.body).toMatchObject({ page: 2, text: "16 weeks of fully", note: "ask HR", color: "green" });
    const rect = (post?.body as { rects: Record<string, number>[] }).rects[0];
    expect(rect?.x).toBeCloseTo(0.1);
    expect(rect?.y).toBeCloseTo(0.125);
    expect(rect?.w).toBeCloseTo(0.5);
    expect(await screen.findByText("Your highlights (1)")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Save highlight" })).not.toBeInTheDocument();
  });

  it("ignores a collapsed selection and lets the reader cancel", async () => {
    const { container } = renderViewer();
    await ready();
    await waitFor(() => expect(container.querySelector('[data-page="2"] .textLayer span')).not.toBeNull());
    vi.spyOn(window, "getSelection").mockReturnValue({ isCollapsed: true, rangeCount: 0 } as unknown as Selection);
    fireEvent.mouseUp(screen.getByRole("region", { name: "PDF pages" }));
    expect(screen.queryByRole("group", { name: "Save highlight" })).not.toBeInTheDocument();
    selectOnPage(container, 2);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("group", { name: "Save highlight" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("lists existing highlights, draws them on the page and jumps to them", async () => {
    stored = [annotation(), annotation({ id: "a2", page: 3, text: "HR portal", note: "", color: "pink" })];
    const { container } = renderViewer({ initialPage: 1, quote: undefined });
    await ready();
    expect(await screen.findByText("Your highlights (2)")).toBeInTheDocument();
    expect(container.querySelectorAll('[data-annotation-id="a1"]')).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: /p\. 3: “HR portal”/ }));
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
  });

  it("edits a note and deletes a highlight", async () => {
    stored = [annotation()];
    renderViewer();
    await ready();
    await userEvent.click(await screen.findByRole("button", { name: "Edit note on page 2" }));
    const field = screen.getByLabelText("Note for the highlight on page 2");
    await userEvent.clear(field);
    await userEvent.type(field, "updated");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.url).toMatch(/\/annotations\/a1$/);
    expect(patch?.body).toEqual({ note: "updated" });
    expect(await screen.findByText("updated")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete highlight on page 2" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByText("Your highlights (0)")).toBeInTheDocument();
  });

  it("shows an error when saving fails", async () => {
    const { container } = renderViewer();
    await ready();
    await waitFor(() => expect(container.querySelector('[data-page="2"] .textLayer span')).not.toBeNull());
    const base = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      if (input instanceof Request && input.method === "POST") {
        return new Response(JSON.stringify({ code: "not_found", detail: "Document not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
      return base(input, init);
    });
    selectOnPage(container, 2);
    await userEvent.click(await screen.findByRole("button", { name: "Save highlight" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Document not found");
  });
});
