import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { answer } from "../test/factories";
import { AskPage } from "./AskPage";

vi.mock("../auth/WorkspaceContext", () => ({
  useWorkspace: () => ({
    workspaces: [],
    current: { id: "w1", name: "Acme", role: "member", created_at: "x" },
    isAdmin: false,
    loading: false,
    select: vi.fn(),
  }),
}));

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const STATUS = { enabled: true, private_mode: true, default_scope: "internal", sources: ["arxiv", "crossref"], hosted_model_for_public: true };

function stub(options: { enabled?: boolean; preview?: unknown } = {}) {
  const fetchMock = vi.fn(async (input: Request | string, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.endsWith("/public-research/preview")) return json(options.preview ?? { query: "sparse attention memory", allowed: true, reasons: [], explanation: "" });
    if (url.endsWith("/public-research")) return json(options.enabled === false ? { ...STATUS, enabled: false, sources: [] } : STATUS);
    if (url.includes("/ask/stream")) return new Response(frame("final", answer({ scope: "both" })), { status: 200, headers: { "Content-Type": "text/event-stream" } });
    if (url.includes("/threads")) return json([]);
    return json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function bodyOf(fetchMock: ReturnType<typeof stub>, path: string) {
  const call = fetchMock.mock.calls.find(([input]) => String(typeof input === "string" ? input : input.url).includes(path));
  const input = call?.[0];
  return JSON.parse(typeof input === "string" ? String((call?.[1] as RequestInit).body) : await input!.clone().text());
}

function renderPage() {
  setAuthToken("tok");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AskPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("AskPage scope", () => {
  it("offers no scope choice when the server has the public lane off", async () => {
    stub({ enabled: false });
    renderPage();
    await screen.findByLabelText("Your question");
    await waitFor(() => expect(screen.queryByTestId("scope-picker")).not.toBeInTheDocument());
  });

  it("keeps questions internal by default and sends no scope", async () => {
    const fetchMock = stub();
    renderPage();
    expect(await screen.findByTestId("scope-picker")).toHaveTextContent("Private mode");
    await userEvent.type(screen.getByLabelText("Your question"), "How many vacation days do I get?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(/Primary caregivers receive/);
    const body = await bodyOf(fetchMock, "/ask/stream");
    expect(body.scope).toBeUndefined();
    expect(body.public_query).toBeUndefined();
  });

  it("previews the keywords, lets the user edit them, and sends exactly the edited query", async () => {
    const fetchMock = stub();
    renderPage();
    await screen.findByTestId("scope-picker");
    await userEvent.click(screen.getByRole("radio", { name: "Both" }));
    await userEvent.type(screen.getByLabelText("Your question"), "How does sparse attention reduce memory?");
    await userEvent.click(screen.getByRole("button", { name: "Preview what will be sent" }));

    const input = await screen.findByLabelText(/Public search keywords/);
    expect(input).toHaveValue("sparse attention memory");
    expect(screen.getByTestId("preview")).toHaveTextContent("Allowed");
    await userEvent.clear(input);
    await userEvent.type(input, "sparse attention efficiency");

    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(/Primary caregivers receive/);
    expect(await bodyOf(fetchMock, "/ask/stream")).toMatchObject({ scope: "both", public_query: "sparse attention efficiency" });
  });

  it("shows why a query was blocked, without echoing it", async () => {
    stub({ preview: { query: "Phoenix attention", allowed: false, reasons: ["company_content"], explanation: "it appears to contain company-sensitive content" } });
    renderPage();
    await screen.findByTestId("scope-picker");
    await userEvent.click(screen.getByRole("radio", { name: "Published research" }));
    await userEvent.type(screen.getByLabelText("Your question"), "What is Phoenix doing about attention?");
    await userEvent.click(screen.getByRole("button", { name: "Preview what will be sent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("company-sensitive content");
  });
});
