import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Dashboard } from "../api/hooksAdmin";
import { DashboardPage } from "./DashboardPage";

const board: Dashboard = {
  workspace_id: "w1",
  days: 30,
  generated_at: "2026-10-25T10:00:00Z",
  questions: { total: 40, answered: 30, refused: 10, refusal_rate: 0.25, claims_shown: 90, claims_dropped: 10, dropped_claim_rate: 0.1 },
  per_day: [
    { date: "2026-10-24", questions: 15, answered: 10, refused: 5, cost_usd: 0.1 },
    { date: "2026-10-25", questions: 25, answered: 20, refused: 5, cost_usd: 0.2 },
  ],
  latency: { p50_ms: 850, p95_ms: 2400 },
  cost: { total_usd: 0.3, per_question_usd: 0.0075, tokens_in: 12000, tokens_out: 3000 },
  documents: { total: 6, chunks: 120, by_status: [{ label: "ready", count: 5 }, { label: "failed", count: 1 }] },
  ingest: {
    failed_documents: 1,
    failed_jobs: 2,
    recent_failures: [{ document_id: "d1", title: "Scan.pdf", error: "The PDF has no extractable text", created_at: "2026-10-25T09:00:00Z" }],
  },
  egress: [{ destination: "api.openalex.org", status: "sent", count: 7 }],
  feedback: { up: 3, down: 1, positive_ratio: 0.75 },
};

let data: Dashboard | undefined = board;
vi.mock("../api/hooksAdmin", () => ({ useDashboard: () => ({ data, isLoading: false, error: null }) }));
vi.mock("../auth/WorkspaceContext", () => ({ useWorkspace: () => ({ current: { id: "w1", name: "Acme", role: "admin" } }) }));

beforeEach(() => {
  data = board;
});

describe("DashboardPage", () => {
  it("shows the key numbers as tiles", () => {
    render(<DashboardPage />);
    const tiles = within(screen.getByRole("region", { name: "Key numbers" }));
    expect(tiles.getByText("Refusal rate").parentElement).toHaveTextContent("25%");
    expect(tiles.getByText("Dropped-claim rate").parentElement).toHaveTextContent("10%");
    expect(tiles.getByText("Latency p50 / p95").parentElement).toHaveTextContent("850 ms / 2.4 s");
    expect(tiles.getByText("Cost").parentElement).toHaveTextContent("$0.30");
    expect(tiles.getByText("Feedback").parentElement).toHaveTextContent("75%");
  });

  it("draws the charts as SVG with text alternatives and a table view", async () => {
    render(<DashboardPage />);
    const chart = screen.getByRole("img", { name: /Questions per day, 40 in total/ });
    expect(chart.tagName.toLowerCase()).toBe("svg");
    expect(chart.querySelectorAll("rect.bar-1").length).toBe(2);
    expect(screen.getByRole("img", { name: "Outbound requests to public sources" })).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Show as table" })[0]!);
    const table = screen.getByRole("table");
    expect(within(table).getByText("Oct 25")).toBeInTheDocument();
  });

  it("lists ingestion failures and says when nothing left the system", () => {
    data = { ...board, egress: [] };
    render(<DashboardPage />);
    expect(screen.getByText("Scan.pdf")).toBeInTheDocument();
    expect(screen.getByText("The PDF has no extractable text")).toBeInTheDocument();
    expect(screen.getByText("Nothing left the system in this period.")).toBeInTheDocument();
  });

  it("never loads anything from the network by itself", () => {
    const { container } = render(<DashboardPage />);
    expect(container.querySelector("script[src], link[href], img[src]")).toBeNull();
  });
});
