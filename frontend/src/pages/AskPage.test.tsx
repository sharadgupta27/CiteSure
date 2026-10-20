import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAuthToken } from "../api/client";
import { answer, citation, claim } from "../test/factories";
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
const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function stubBackend(streamBody: string) {
  const fetchMock = vi.fn(async (input: Request | string, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.includes("/ask/stream")) {
      return new Response(streamBody, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    }
    if (url.includes("/threads")) return jsonResponse([]);
    if (url.includes("/feedback")) return jsonResponse({ id: "f1", answer_id: "a1", user_id: "u1", rating: 1, comment: null, created_at: "x" });
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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

describe("AskPage", () => {
  it("streams an answer and shows it with citation chips", async () => {
    const final = answer({ claims: [claim("Primary caregivers receive 16 weeks of paid leave.", [citation()])] });
    const body =
      frame("stage", "retrieving") + frame("stage", "generating") + frame("stage", "verifying") + frame("token", "Primary caregivers ") + frame("final", final);
    const fetchMock = stubBackend(body);
    renderPage();

    await userEvent.type(screen.getByLabelText("Your question"), "How many weeks of paid parental leave?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Primary caregivers receive 16 weeks of paid leave\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source 1" })).toBeInTheDocument();
    const streamCall = fetchMock.mock.calls.find(([input]) => String(typeof input === "string" ? input : input.url).includes("/ask/stream"));
    expect(JSON.parse(String((streamCall?.[1] as RequestInit).body))).toMatchObject({ workspace_id: "w1", question: "How many weeks of paid parental leave?" });
  });

  it("shows a refusal when the documents do not contain the answer", async () => {
    const refused = answer({
      status: "refused",
      claims: [],
      refusal: { reason: "no_supported_claims", message: "I don't have information on that in the documents available to you.", closest_sources: [] },
    });
    stubBackend(frame("stage", "retrieving") + frame("final", refused));
    renderPage();
    await userEvent.type(screen.getByLabelText("Your question"), "What is the sabbatical policy?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByTestId("refusal")).toHaveTextContent("I don't have information on that");
  });

  it("shows a readable error when the server rejects the question", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: Request | string) => {
        const url = typeof input === "string" ? input : input.url;
        if (url.includes("/ask/stream")) return new Response(JSON.stringify({ code: "rate_limited", detail: "Too many requests. Please slow down." }), { status: 429 });
        return jsonResponse([]);
      }),
    );
    renderPage();
    await userEvent.type(screen.getByLabelText("Your question"), "Another question please");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
  });

  it("does not send questions that are too short", async () => {
    stubBackend("");
    renderPage();
    await userEvent.type(screen.getByLabelText("Your question"), "hi");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("lets the user rate the latest answer", async () => {
    const fetchMock = stubBackend(frame("final", answer()));
    renderPage();
    await userEvent.type(screen.getByLabelText("Your question"), "How many weeks of paid parental leave?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: "Thumbs up" }));
    expect(await screen.findByText(/your feedback was saved/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(typeof input === "string" ? input : input.url).includes("/answers/a1/feedback"))).toBe(true);
  });
});
