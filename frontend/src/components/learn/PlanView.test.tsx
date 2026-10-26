import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { answer, citation, claim } from "../../test/factories";
import { PlanView } from "./PlanView";

const toggle = vi.fn();
const plan = {
  id: "p1",
  workspace_id: "w1",
  study_set_id: null,
  title: "Security basics",
  topic: null,
  hours_per_week: 4,
  weeks: 2,
  total_minutes: 90,
  steps_done: 1,
  steps_total: 2,
  percent: 50,
  created_at: "x",
  steps: [
    {
      id: "s1",
      position: 1,
      week: 1,
      document_id: "d1",
      document_title: "Phishing Policy",
      label: "Reporting",
      page_start: 1,
      page_end: 3,
      est_minutes: 30,
      done: true,
      done_at: "x",
      reading_percent: 100,
      objective: answer({ claims: [claim("Report phishing within one hour.", [citation()])] }),
    },
    {
      id: "s2",
      position: 2,
      week: 2,
      document_id: "d2",
      document_title: "Travel Policy",
      label: "",
      page_start: null,
      page_end: null,
      est_minutes: 60,
      done: false,
      done_at: null,
      reading_percent: 0,
      objective: answer({
        status: "refused",
        claims: [],
        refusal: { reason: "no_supported_claims", message: "Nothing supported.", closest_sources: [] },
      }),
    },
  ],
};

vi.mock("../../api/hooksLearning", () => ({
  useLearningPlan: () => ({ data: plan, isLoading: false, error: null }),
  useSetPlanStepDone: () => ({ mutate: toggle, isPending: false, error: null }),
  useDeletePlan: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("../SourceViewer", () => ({ SourceViewer: () => null }));

function renderView() {
  render(
    <MemoryRouter>
      <PlanView planId="p1" workspaceId="w1" />
    </MemoryRouter>,
  );
}

describe("PlanView", () => {
  it("shows overall progress and steps grouped by week", () => {
    renderView();
    expect(screen.getByText(/1 of 2 steps done \(50%\)/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Plan progress" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByRole("region", { name: "Week 1" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Week 2" })).toBeInTheDocument();
    expect(screen.getByText("1 h")).toBeInTheDocument();
  });

  it("renders the objective through AnswerView, with citation chips and refusals", () => {
    renderView();
    const week1 = screen.getByRole("region", { name: "Week 1" });
    expect(within(week1).getByText(/Report phishing within one hour/)).toBeInTheDocument();
    expect(within(week1).getByRole("button", { name: "Open source 1" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Week 2" })).getByTestId("refusal")).toBeInTheDocument();
  });

  it("calls the mutation when a step checkbox is toggled", async () => {
    renderView();
    await userEvent.click(screen.getByRole("checkbox", { name: /Mark step 2 done: Travel Policy/ }));
    expect(toggle).toHaveBeenCalledWith({ stepId: "s2", done: true });
    await userEvent.click(screen.getByRole("checkbox", { name: /Mark step 1 done: Phishing Policy/ }));
    expect(toggle).toHaveBeenCalledWith({ stepId: "s1", done: false });
  });
});
