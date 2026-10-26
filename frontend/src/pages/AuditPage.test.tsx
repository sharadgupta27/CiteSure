import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AuditEvent } from "../api/hooksAdmin";
import { AuditPage, toFilters } from "./AuditPage";

const event = (seq: number, action: string): AuditEvent => ({
  seq,
  created_at: "2026-10-25T10:00:00Z",
  actor_id: "u1",
  actor_email: "admin@acme.example",
  action,
  target: `document:${seq}`,
  workspace_id: "w1",
  metadata: { bytes: 10 },
  hash: "h".repeat(64),
});

const verify = vi.fn();
const verifyState: { data?: object; error: unknown; isPending: boolean } = { error: null, isPending: false };
const useAuditEvents = vi.fn();
const downloadAuditCsv = vi.fn();

vi.mock("../api/hooksAdmin", () => ({
  AUDIT_PAGE_SIZE: 25,
  useAuditEvents: (...args: unknown[]) => useAuditEvents(...args),
  useVerifyAuditChain: () => ({ mutate: verify, ...verifyState }),
  downloadAuditCsv: (...args: unknown[]) => downloadAuditCsv(...args),
}));
vi.mock("../auth/WorkspaceContext", () => ({ useWorkspace: () => ({ current: { id: "w1", name: "Acme", role: "admin" } }) }));

beforeEach(() => {
  verify.mockReset();
  downloadAuditCsv.mockReset();
  verifyState.data = undefined;
  useAuditEvents.mockReset();
  useAuditEvents.mockReturnValue({
    data: { items: [event(2, "document.delete"), event(1, "document.upload")], total: 60, limit: 25, offset: 0 },
    isLoading: false,
    error: null,
  });
});

describe("AuditPage", () => {
  it("lists entries, newest first, with paging", async () => {
    render(<AuditPage />);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3); // header + two entries
    expect(rows[1]).toHaveTextContent("document.delete");
    expect(screen.getByText("1 to 2 of 60")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Newer" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Older" }));
    expect(useAuditEvents).toHaveBeenLastCalledWith("w1", {}, 25);
  });

  it("sends the chosen filters and returns to the first page", async () => {
    render(<AuditPage />);
    await userEvent.type(screen.getByLabelText("Person (e-mail or id)"), "admin@");
    await userEvent.selectOptions(screen.getByLabelText("Action"), "document.delete");
    await userEvent.click(screen.getByRole("button", { name: "Filter" }));
    expect(useAuditEvents).toHaveBeenLastCalledWith("w1", { actor: "admin@", action: "document.delete" }, 0);
  });

  it("turns the dates into an inclusive range", () => {
    const filters = toFilters({ actor: "", action: "", since: "2026-10-01", until: "2026-10-02" });
    expect(new Date(filters.until!).getTime() - new Date(filters.since!).getTime()).toBeGreaterThanOrEqual(2 * 23 * 3600 * 1000);
    expect(toFilters({ actor: " ", action: "", since: "", until: "" })).toEqual({});
  });

  it("verifies the chain and reports a break loudly", async () => {
    verifyState.data = { ok: false, checked: 3, head_seq: null, head_hash: null, first_bad_seq: 4, reason: "the entry was changed after it was written", starts_at_seq: 1 };
    render(<AuditPage />);
    await userEvent.click(screen.getByRole("button", { name: "Verify chain" }));
    expect(verify).toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("broken at entry #4");
  });

  it("reports an intact chain with the head hash to keep", () => {
    verifyState.data = { ok: true, checked: 120, head_seq: 120, head_hash: "abc123", first_bad_seq: null, reason: null, starts_at_seq: 1 };
    render(<AuditPage />);
    expect(screen.getByRole("status")).toHaveTextContent("120 entries checked");
    expect(screen.getByRole("status")).toHaveTextContent("abc123");
  });

  it("exports the current filter as CSV", async () => {
    downloadAuditCsv.mockResolvedValue(new Blob(["seq\n"]));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<AuditPage />);
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(downloadAuditCsv).toHaveBeenCalledWith("w1", {});
    click.mockRestore();
  });
});
