import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken, type Schemas } from "../api/client";
import { citation } from "../test/factories";
import { PublicSourceActions } from "./PublicSourceActions";

const workspace = vi.hoisted(() => ({ current: { id: "w1" } as { id: string } | undefined }));
vi.mock("../auth/WorkspaceContext", () => ({ useWorkspace: () => ({ current: workspace.current }) }));

type Status = Schemas["FullTextStatus"];
const REQUEST_ID = "11111111-1111-4111-8111-111111111111";
const PAPER = citation({ source_type: "public", url: "https://doi.org/10.1000/abc", document_title: "Sparse attention (Hopper, 2023)" });

const status = (overrides: Partial<Status> = {}): Status => ({
  id: REQUEST_ID,
  status: "queued",
  title: null,
  passages: null,
  pages: null,
  cached: false,
  error: null,
  message: null,
  fetches_remaining: 19,
  egress: [],
  ...overrides,
});
const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

interface Calls {
  posts: unknown[];
  gets: number;
}

/** A tiny fake server: the POST returns `first`, every later GET returns the next entry of `polls` (the last repeats). */
function serve(first: Response | Status, polls: Status[] = []): Calls {
  const calls: Calls = { posts: [], gets: 0 };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      if (request.method === "POST") {
        calls.posts.push(await request.json());
        return first instanceof Response ? first.clone() : json(first);
      }
      const reply = polls[Math.min(calls.gets, polls.length - 1)];
      calls.gets += 1;
      return json(reply);
    }),
  );
  return calls;
}

function renderActions(cited = PAPER) {
  setAuthToken("tok");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PublicSourceActions citation={cited} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  workspace.current = { id: "w1" };
});
afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("PublicSourceActions", () => {
  it("offers to fetch the full text and sends the paper's address with the workspace", async () => {
    const calls = serve(status({ status: "ready", cached: true, passages: 42, pages: 9, title: "Sparse attention (Hopper, 2023)" }));
    renderActions();
    expect(screen.getByRole("button", { name: "Fetch full text" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Fetch full text" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Full text added: 42 passages from 9 pages; ask again to use it.");
    expect(calls.posts).toEqual([{ workspace_id: "w1", url: "https://doi.org/10.1000/abc" }]);
    expect(screen.queryByRole("button", { name: "Fetch full text" })).not.toBeInTheDocument();
  });

  it("shows progress while the worker downloads, then the result", async () => {
    const calls = serve(status(), [status(), status({ status: "running" }), status({ status: "ready", passages: 12, pages: 4 })]);
    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Fetch full text" }));
    expect(await screen.findByText("Waiting for the worker…")).toBeInTheDocument();
    expect(await screen.findByText("Downloading and indexing the paper…", undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(await screen.findByText(/Full text added: 12 passages from 4 pages/, undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(calls.gets).toBeGreaterThanOrEqual(2);
  }, 10_000);

  it("says which hosts were contacted and that only an identifier was sent", async () => {
    serve(
      status({
        status: "ready",
        passages: 3,
        egress: [
          { destination: "api.openalex.org", status: "sent", query: "10.1000/abc", reason: null },
          { destination: "arxiv.org", status: "sent", query: "10.1000/abc", reason: null },
          { destination: "arxiv.org", status: "failed", query: "10.1000/abc", reason: "timeout" },
        ],
      }),
    );
    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Fetch full text" }));
    const note = await screen.findByTestId("fulltext-egress");
    expect(note).toHaveTextContent("Contacted: api.openalex.org, arxiv.org.");
    expect(note).toHaveTextContent("no question or document text");
  });

  it("explains a failure in plain words and lets the user try again", async () => {
    serve(
      status({
        status: "failed",
        error: "no_open_access",
        message: "No open-access PDF was found for this paper. The abstract stays available.",
        fetches_remaining: 18,
      }),
    );
    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Fetch full text" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No open-access PDF was found for this paper");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
    expect(screen.getByText("18 full-text downloads left today in this workspace.")).toBeInTheDocument();
  });

  it("shows the budget message when the workspace is out of downloads", async () => {
    serve(
      json(
        { code: "fulltext_budget_exceeded", detail: "This workspace has used its 20 open-access downloads for today." },
        429,
      ),
    );
    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Fetch full text" }));
    expect(await screen.findByTestId("fulltext-budget")).toHaveTextContent("used its 20 open-access downloads for today");
    expect(screen.getByRole("button", { name: "Fetch full text" })).toBeEnabled();
  });

  it("shows other server errors, such as the feature being off", async () => {
    serve(json({ code: "invalid_input", detail: "Open-access full text is not turned on for this server." }, 422));
    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Fetch full text" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not turned on for this server");
  });

  it("cannot fetch without a workspace or without an address", () => {
    workspace.current = undefined;
    renderActions();
    expect(screen.getByRole("button", { name: "Fetch full text" })).toBeDisabled();
    expect(screen.getByText("Select a workspace to fetch full text.")).toBeInTheDocument();
  });

  it("explains when the citation has no address", () => {
    renderActions(citation({ source_type: "public", url: null }));
    expect(screen.getByRole("button", { name: "Fetch full text" })).toBeDisabled();
    expect(screen.getByText(/has no address/)).toBeInTheDocument();
  });
});
