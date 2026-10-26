import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { citation } from "../test/factories";
import { SourceViewer } from "./SourceViewer";

vi.mock("pdfjs-dist", async () => (await import("../test/fakePdfjs")).fakePdfjs);
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/assets/pdf.worker.js" }));

const TEXT = "Primary caregivers receive 16 weeks of fully paid leave. Secondary caregivers receive 8 weeks.";
const chunk = {
  id: "c1",
  document_id: "d1",
  document_title: "Parental Leave Policy",
  collection_id: "col1",
  ord: 0,
  text: TEXT,
  heading_path: ["Parental Leave Policy"],
  page_start: 2,
  page_end: 2,
  char_start: 0,
  char_end: TEXT.length,
};
const documentRecord = (mime: string) => ({
  id: "d1",
  collection_id: "col1",
  title: "Parental Leave Policy",
  filename: "policy",
  mime,
  sha256: "abc",
  status: "ready",
  page_count: 3,
  chunk_count: 1,
  error: null,
  created_at: "2026-10-20T10:00:00Z",
});

let requested: string[] = [];

function setup(mime: string, page: number | null = 2) {
  requested = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      requested.push(url);
      const path = new URL(url, "http://localhost").pathname;
      const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path.endsWith("/chunks")) return json([{ ...chunk, page_start: page }]);
      if (path.endsWith("/file")) return new Response(new ArrayBuffer(16), { status: 200 });
      if (path.endsWith("/annotations")) return json([]);
      if (path === "/api/v1/documents/d1") return json(documentRecord(mime));
      return new Response("{}", { status: 404 });
    }),
  );
  setAuthToken("tok");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as CanvasRenderingContext2D);
  const start = TEXT.indexOf("16 weeks");
  const cited = citation({
    chunk_id: "c1",
    page_start: page,
    page_end: page,
    quote_start: start,
    quote_end: start + "16 weeks of fully paid leave".length,
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SourceViewer citation={cited} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("SourceViewer with a PDF", () => {
  it("opens the PDF tab by default with the cited page", async () => {
    setup("application/pdf");
    const tablist = await screen.findByRole("tablist", { name: "Source view" });
    expect(tablist).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "PDF" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Text" })).toHaveAttribute("aria-selected", "false");
    expect(await screen.findByRole("region", { name: "PDF pages" })).toBeInTheDocument();
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "PDF" })).toBeInTheDocument();
  });

  it("switches to the Text tab with the arrow keys and shows the highlighted chunk", async () => {
    setup("application/pdf");
    const pdfTab = await screen.findByRole("tab", { name: "PDF" });
    pdfTab.focus();
    await userEvent.keyboard("{ArrowRight}");
    const textTab = screen.getByRole("tab", { name: "Text" });
    expect(textTab).toHaveAttribute("aria-selected", "true");
    expect(textTab).toHaveFocus();
    expect(screen.queryByRole("region", { name: "PDF pages" })).not.toBeInTheDocument();
    const mark = await screen.findByText("16 weeks of fully paid leave");
    expect(mark.tagName).toBe("MARK");
    expect(screen.getByRole("button", { name: "Show the whole document" })).toBeInTheDocument();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "PDF" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("region", { name: "PDF pages" })).toBeInTheDocument();
  });

  it("uses roving tabindex on the tabs", async () => {
    setup("application/pdf");
    expect(await screen.findByRole("tab", { name: "PDF" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Text" })).toHaveAttribute("tabindex", "-1");
  });

  it("only fetches same-origin API paths (no CDN, no external host)", async () => {
    setup("application/pdf");
    await screen.findByText("Page 2 of 3");
    await waitFor(() => expect(requested.some((u) => u.endsWith("/documents/d1/file"))).toBe(true));
    for (const url of requested) {
      const parsed = new URL(url, window.location.origin);
      expect(parsed.origin).toBe(window.location.origin);
      expect(parsed.pathname.startsWith("/api/v1/")).toBe(true);
    }
  });

  it("keeps the plain text view, without tabs, for a document that is not a PDF", async () => {
    setup("text/markdown");
    const mark = await screen.findByText("16 weeks of fully paid leave");
    expect(mark.tagName).toBe("MARK");
    await waitFor(() => expect(requested.some((u) => u.endsWith("/documents/d1"))).toBe(true));
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "PDF pages" })).not.toBeInTheDocument();
    expect(requested.some((u) => u.endsWith("/file"))).toBe(false);
  });

  it("does not ask for the document record when nothing has a page number", async () => {
    setup("application/pdf", null);
    await screen.findByText("16 weeks of fully paid leave");
    expect(requested.some((u) => u.endsWith("/api/v1/documents/d1"))).toBe(false);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
