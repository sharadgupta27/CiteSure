import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { answer } from "../../test/factories";
import { AgentLauncher } from "./AgentLauncher";

const docs = [
  { id: "d1", title: "Policy A", status: "ready" },
  { id: "d2", title: "Policy B", status: "ready" },
  { id: "d3", title: "Policy C", status: "queued" },
];
const compareMutate = vi.fn();
const summarizeMutate = vi.fn();

vi.mock("../../api/hooks", () => ({
  useCollections: () => ({ data: [{ id: "c1", name: "General" }], isLoading: false }),
  useDocuments: () => ({ data: docs, isLoading: false }),
}));
vi.mock("../../api/hooksLearning", () => ({
  useSummarize: () => ({ mutate: summarizeMutate, isPending: false, error: null }),
  useCompare: () => ({ mutate: compareMutate, isPending: false, error: null }),
}));
vi.mock("../SourceViewer", () => ({ SourceViewer: () => null }));

describe("AgentLauncher", () => {
  it("only offers documents that are ready", () => {
    render(<AgentLauncher workspaceId="w1" />);
    expect(screen.queryByLabelText("Policy C")).not.toBeInTheDocument();
  });

  it("needs two documents and an aspect before comparing", async () => {
    render(<AgentLauncher workspaceId="w1" />);
    await userEvent.click(screen.getByRole("tab", { name: "Compare" }));
    const run = screen.getByRole("button", { name: "Compare" });
    expect(run).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Aspect to compare"), "data retention");
    await userEvent.click(screen.getByLabelText("Policy A"));
    expect(run).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Policy B"));
    expect(run).toBeEnabled();
    await userEvent.click(run);
    expect(compareMutate).toHaveBeenCalledWith({ document_ids: ["d1", "d2"], aspect: "data retention" }, expect.anything());
  });

  it("shows a refusal returned by the server", async () => {
    summarizeMutate.mockImplementation((_body, options) =>
      options.onSuccess(
        answer({
          status: "refused",
          claims: [],
          refusal: { reason: "no_supported_claims", message: "Nothing supported.", closest_sources: [] },
        }),
      ),
    );
    render(<AgentLauncher workspaceId="w1" />);
    await userEvent.click(screen.getByLabelText("Policy A"));
    await userEvent.click(screen.getByRole("button", { name: "Summarize" }));
    expect(summarizeMutate).toHaveBeenCalledWith({ document_id: "d1", focus: null }, expect.anything());
    expect(await screen.findByTestId("refusal")).toHaveTextContent("Nothing supported.");
  });
});
