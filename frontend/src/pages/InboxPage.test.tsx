import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { InboxPage } from "./InboxPage";

vi.mock("../auth/WorkspaceContext", () => ({
  useWorkspace: () => ({
    workspaces: [],
    current: { id: "w1", name: "Acme", role: "admin", created_at: "x" },
    isAdmin: true,
    loading: false,
    select: vi.fn(),
  }),
}));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const STATUS = {
  enabled: true,
  workspace_folder: "acme",
  poll_seconds: 30,
  max_file_mb: 20,
  allowed_types: ["pdf", "docx"],
  last_scan_at: "2026-10-25T10:00:00Z",
  scan_requested: false,
  folders: [
    {
      folder: "acme/Policies",
      collection_id: "c1",
      collection_name: "Policies",
      matched: true,
      imported: 3,
      duplicates: 1,
      quarantined: 0,
      failed: 0,
      last_activity_at: "2026-10-25T09:00:00Z",
    },
    {
      folder: "acme/Polcies",
      collection_id: null,
      collection_name: null,
      matched: false,
      imported: 0,
      duplicates: 0,
      quarantined: 2,
      failed: 0,
      last_activity_at: null,
    },
  ],
};

const item = (over: Record<string, unknown>) => ({
  id: "i1",
  folder: "acme/Policies",
  filename: "leave.pdf",
  size_bytes: 2048,
  status: "imported",
  reason: null,
  collection_id: "c1",
  collection_name: "Policies",
  document_id: "d1",
  document_status: "ready",
  created_at: "2026-10-25T09:00:00Z",
  ...over,
});

const ITEMS = [
  item({}),
  item({
    id: "i2",
    folder: "acme/Polcies",
    filename: "typo.pdf",
    status: "quarantined",
    reason: "No collection in this workspace matches this folder name",
    collection_id: null,
    collection_name: null,
    document_id: null,
    document_status: null,
  }),
];

function stub(options: { status?: unknown; items?: unknown[] } = {}) {
  const fetchMock = vi.fn(async (input: Request | string) => {
    const request = typeof input === "string" ? null : input;
    const url = request ? request.url : String(input);
    if (url.includes("/inbox/scan")) return json({ ...STATUS, scan_requested: true }, 202);
    if (url.includes("/inbox/items")) {
      const wanted = new URL(url).searchParams.get("status");
      return json((options.items ?? ITEMS).filter((i) => !wanted || (i as { status: string }).status === wanted));
    }
    if (url.endsWith("/inbox")) return json(options.status ?? STATUS);
    return json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  setAuthToken("tok");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <InboxPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("InboxPage", () => {
  it("explains the layout and lists folders with their counts", async () => {
    stub();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Watched folders" })).toBeInTheDocument();
    const folders = await screen.findByRole("table", { name: /Watched folders and what happened/ });
    const row = within(folders).getByText("acme/Policies").closest("tr")!;
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/up to 20 MB/)).toBeInTheDocument();
  });

  it("flags folders that match no collection and warns about quarantined files", async () => {
    stub();
    renderPage();
    expect(await screen.findByText("no matching collection")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("2 files were quarantined");
  });

  it("lists recent files with the reason a file was quarantined", async () => {
    stub();
    renderPage();
    const table = await screen.findByRole("table", { name: /Files the watcher has looked at/ });
    expect(within(table).getByText("leave.pdf")).toBeInTheDocument();
    expect(within(table).getByText("typo.pdf")).toBeInTheDocument();
    expect(within(table).getByText(/matches this folder name/)).toBeInTheDocument();
    expect(within(table).getByText("document: ready")).toBeInTheDocument();
  });

  it("filters by status", async () => {
    const fetchMock = stub();
    renderPage();
    await screen.findByText("typo.pdf");
    await userEvent.click(screen.getByRole("button", { name: "Quarantined" }));
    await waitFor(() => expect(screen.queryByText("leave.pdf")).not.toBeInTheDocument());
    expect(screen.getByText("typo.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quarantined" })).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock.mock.calls.some(([i]) => String((i as Request).url).includes("status=quarantined"))).toBe(true);
  });

  it("asks the worker for a scan", async () => {
    const fetchMock = stub();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Scan now" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([i]) => (i as Request).method === "POST" && String((i as Request).url).endsWith("/workspaces/w1/inbox/scan"))).toBe(true),
    );
  });

  it("says so when the feature is switched off, and offers no scan button", async () => {
    stub({ status: { ...STATUS, enabled: false, folders: [] } });
    renderPage();
    expect(await screen.findByText(/switched off/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scan now" })).not.toBeInTheDocument();
  });

  it("only talks to the same-origin API", async () => {
    const fetchMock = stub();
    renderPage();
    await screen.findByText("typo.pdf");
    for (const [input] of fetchMock.mock.calls) expect(new URL(String((input as Request).url)).pathname).toMatch(/^\/api\/v1\//);
  });
});
