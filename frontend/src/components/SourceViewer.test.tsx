import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { citation } from "../test/factories";
import { SourceViewer } from "./SourceViewer";

const TEXT = "Primary caregivers receive 16 weeks of fully paid leave. Secondary caregivers receive 8 weeks.";
const chunk = (id: string, text: string, ord: number) => ({
  id,
  document_id: "d1",
  document_title: "Parental Leave Policy",
  collection_id: "col1",
  ord,
  text,
  heading_path: ["Parental Leave Policy"],
  page_start: null,
  page_end: null,
  char_start: 0,
  char_end: text.length,
});

function renderViewer(onClose = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify([chunk("c1", TEXT, 0), chunk("c2", "A second chunk of the document.", 1)]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  setAuthToken("tok");
  const start = TEXT.indexOf("16 weeks");
  const cited = citation({ chunk_id: "c1", quote_start: start, quote_end: start + "16 weeks of fully paid leave".length });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SourceViewer citation={cited} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("SourceViewer", () => {
  it("highlights exactly the quoted words in the cited passage", async () => {
    renderViewer();
    const mark = await screen.findByText("16 weeks of fully paid leave");
    expect(mark.tagName).toBe("MARK");
    expect(screen.getByTestId("cited-chunk")).toHaveTextContent(TEXT);
    expect(screen.queryByText(/A second chunk/)).not.toBeInTheDocument();
  });

  it("can show the rest of the document", async () => {
    renderViewer();
    await screen.findByText("16 weeks of fully paid leave");
    await userEvent.click(screen.getByRole("button", { name: "Show the whole document" }));
    expect(await screen.findByText(/A second chunk/)).toBeInTheDocument();
  });

  it("closes with the close button and with Escape", async () => {
    const onClose = renderViewer();
    await screen.findByText("16 weeks of fully paid leave");
    await userEvent.click(screen.getByRole("button", { name: "Close source" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(2));
  });

  it("is an accessible modal dialog", async () => {
    renderViewer();
    const dialog = await screen.findByRole("dialog", { name: "Source" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });
});
