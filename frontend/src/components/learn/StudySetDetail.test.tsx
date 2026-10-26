import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { StudySetDetail } from "./StudySetDetail";

const addItem = vi.fn();
const data = {
  id: "s1",
  workspace_id: "w1",
  name: "Onboarding",
  description: "",
  notes: "",
  item_count: 2,
  progress: { documents_total: 1, documents_started: 1, documents_finished: 0, percent: 40 },
  created_at: "x",
  updated_at: "x",
  items: [
    { id: "i1", position: 0, kind: "document", document_id: "d1", title: "Handbook", url: null, source: null, note: "", page_count: 10, percent: 40, added_at: "x" },
    {
      id: "i2",
      position: 1,
      kind: "reference",
      document_id: null,
      title: "A public paper",
      url: "https://arxiv.org/abs/1",
      source: "arxiv",
      note: "",
      page_count: null,
      percent: null,
      added_at: "x",
    },
  ],
};
const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, error: null };

vi.mock("../../api/hooksLearning", () => ({
  useStudySet: () => ({ data, isLoading: false, error: null }),
  useUpdateStudySet: () => idle,
  useDeleteStudySet: () => idle,
  useAddStudySetItem: () => ({ ...idle, mutate: addItem }),
  useUpdateStudySetItem: () => idle,
  useRemoveStudySetItem: () => idle,
}));
vi.mock("../../api/hooks", () => ({
  useCollections: () => ({ data: [], isLoading: false }),
  useDocuments: () => ({ data: [], isLoading: false }),
}));

function renderDetail() {
  render(
    <MemoryRouter>
      <StudySetDetail setId="s1" />
    </MemoryRouter>,
  );
}

describe("StudySetDetail", () => {
  it("shows per-document and overall progress bars; saved papers have none", () => {
    renderDetail();
    expect(screen.getByRole("progressbar", { name: "Study set progress" })).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByRole("progressbar", { name: "Reading progress in Handbook" })).toHaveAttribute("aria-valuenow", "40");
    expect(screen.queryByRole("progressbar", { name: /A public paper/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A public paper" })).toHaveAttribute("href", "https://arxiv.org/abs/1");
  });

  it("saves a public paper by reference", async () => {
    renderDetail();
    const save = screen.getByRole("button", { name: "Save paper" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Paper title"), "Attention is all you need");
    await userEvent.type(screen.getByLabelText("Paper link"), "https://arxiv.org/abs/1706.03762");
    await userEvent.click(save);
    expect(addItem).toHaveBeenCalledWith(
      { reference: { title: "Attention is all you need", url: "https://arxiv.org/abs/1706.03762" } },
      expect.anything(),
    );
  });
});
