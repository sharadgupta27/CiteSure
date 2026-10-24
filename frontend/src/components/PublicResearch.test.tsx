import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { answer, citation, claim } from "../test/factories";
import { AnswerView } from "./AnswerView";
import { SourceViewer } from "./SourceViewer";

const publicCitation = citation({
  chunk_id: "p1",
  document_id: "pd1",
  document_title: "Block-Sparse Attention (Lovelace et al., 2024)",
  quote: "reduce memory use by forty percent",
  quote_start: 0,
  quote_end: 0,
  heading_path: ["Block-Sparse Attention"],
  source_type: "public",
  url: "https://arxiv.org/abs/2401.00001v1",
});

describe("public research in answers", () => {
  it("marks public sources, names their host, and keeps company sources unmarked", () => {
    render(
      <AnswerView
        answer={answer({ scope: "both", claims: [claim("Block-sparse patterns cut memory.", [publicCitation]), claim("We give 30 days.", [citation()])] })}
        onOpenSource={() => undefined}
      />,
    );
    expect(screen.getAllByText("Public")).toHaveLength(1);
    expect(screen.getByText(/Block-Sparse Attention \(Lovelace et al., 2024\) · arxiv\.org/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source 1" })).toHaveClass("bg-emerald-100");
    expect(screen.getByRole("button", { name: "Open source 2" })).toHaveClass("bg-indigo-100");
  });

  it("shows notices, such as why the public search was skipped", () => {
    render(
      <AnswerView
        answer={answer({ scope: "both", notices: ["The public search was skipped because it appears to contain company-sensitive content."] })}
        onOpenSource={() => undefined}
      />,
    );
    expect(screen.getByTestId("notices")).toHaveTextContent("company-sensitive content");
  });

  it("states exactly which keywords left the system", () => {
    render(
      <AnswerView
        answer={answer({
          scope: "public",
          egress: [
            { destination: "arxiv", status: "sent", query: "sparse attention memory", reason: null },
            { destination: "crossref", status: "sent", query: "sparse attention memory", reason: null },
            { destination: "openalex", status: "failed", query: null, reason: "ConnectError" },
          ],
        })}
        onOpenSource={() => undefined}
      />,
    );
    const disclosure = screen.getByTestId("egress");
    expect(disclosure).toHaveTextContent("keywords sent to arxiv, crossref");
    expect(disclosure).toHaveTextContent("sparse attention memory");
    expect(disclosure).toHaveTextContent("No document text was sent");
    expect(disclosure).toHaveTextContent("openalex did not respond");
  });

  it("says nothing was sent when the guard blocked the query, without the blocked text", () => {
    render(
      <AnswerView
        answer={answer({ egress: [{ destination: "public", status: "blocked", query: null, reason: "company_content" }] })}
        onOpenSource={() => undefined}
      />,
    );
    expect(screen.getByTestId("egress")).toHaveTextContent("nothing was sent");
    expect(screen.getByTestId("egress")).toHaveTextContent("Blocked before sending (company_content)");
  });

  it("shows no egress section for internal-only answers", () => {
    render(<AnswerView answer={answer()} onOpenSource={() => undefined} />);
    expect(screen.queryByTestId("egress")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notices")).not.toBeInTheDocument();
  });
});

describe("SourceViewer for a public source", () => {
  function renderPublic(url: string | null) {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setAuthToken("tok");
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SourceViewer citation={{ ...publicCitation, url }} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    return fetchMock;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    setAuthToken(null);
  });

  it("shows the quote and a safe link to the original, and loads nothing from the server", async () => {
    const fetchMock = renderPublic("https://arxiv.org/abs/2401.00001v1");
    expect(screen.getByText("Public source")).toBeInTheDocument();
    expect(screen.getByTestId("cited-chunk")).toHaveTextContent("reduce memory use by forty percent");
    const link = screen.getByRole("link", { name: /Open the original/ });
    expect(link).toHaveAttribute("href", "https://arxiv.org/abs/2401.00001v1");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Download original/ })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
  });

  it("refuses to turn a javascript: address into a link", () => {
    renderPublic("javascript:alert(1)");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("No address available")).toBeInTheDocument();
  });
});
