import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { answer, citation, claim } from "../test/factories";
import { AnswerView } from "./AnswerView";

describe("AnswerView", () => {
  it("shows every claim with numbered citation chips and a source list", () => {
    const first = citation({ chunk_id: "a", quote: "16 weeks of fully paid leave" });
    const second = citation({ chunk_id: "b", document_title: "Benefits", quote: "401(k) up to 4 percent", heading_path: ["Retirement"] });
    render(
      <AnswerView
        answer={answer({ claims: [claim("Primary caregivers get 16 weeks.", [first]), claim("The match is 4 percent.", [second])] })}
        onOpenSource={() => undefined}
      />,
    );
    expect(screen.getByText(/Primary caregivers get 16 weeks\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source 2" })).toBeInTheDocument();
    const sources = screen.getByRole("list");
    expect(within(sources).getByText(/Benefits › Retirement/)).toBeInTheDocument();
    expect(within(sources).getByText(/“401\(k\) up to 4 percent”/)).toBeInTheDocument();
    expect(screen.getByText(/Every citation was checked/)).toBeInTheDocument();
  });

  it("still renders an answer from a server that predates notices and egress", () => {
    const legacy: Partial<ReturnType<typeof answer>> = answer();
    delete legacy.notices;
    delete legacy.egress;
    render(<AnswerView answer={legacy as ReturnType<typeof answer>} onOpenSource={() => undefined} />);
    expect(screen.getByText(/Primary caregivers receive 16 weeks/)).toBeInTheDocument();
    expect(screen.queryByTestId("notices")).not.toBeInTheDocument();
    expect(screen.queryByTestId("egress")).not.toBeInTheDocument();
  });

  it("opens the matching source when a chip is clicked", async () => {
    const onOpenSource = vi.fn();
    const second = citation({ chunk_id: "b", document_title: "Benefits" });
    render(<AnswerView answer={answer({ claims: [claim("One.", [citation()]), claim("Two.", [second])] })} onOpenSource={onOpenSource} />);
    await userEvent.click(screen.getByRole("button", { name: "Open source 2" }));
    expect(onOpenSource).toHaveBeenCalledWith(second);
  });

  it("tells the reader when unsupported statements were removed", () => {
    render(<AnswerView answer={answer({ dropped_claims: 2 })} onOpenSource={() => undefined} />);
    expect(screen.getByText(/2 statement\(s\) were removed/)).toBeInTheDocument();
  });

  it("renders a refusal with links to the closest readable documents", async () => {
    const onOpenSource = vi.fn();
    render(
      <AnswerView
        answer={answer({
          status: "refused",
          claims: [],
          refusal: {
            reason: "no_supported_claims",
            message: "I don't have information on that in the documents available to you.",
            closest_sources: [{ document_id: "d9", document_title: "Vacation and PTO", chunk_id: "c9" }],
          },
        })}
        onOpenSource={onOpenSource}
      />,
    );
    expect(screen.getByTestId("refusal")).toHaveTextContent("I don't have information on that");
    await userEvent.click(screen.getByRole("button", { name: "Vacation and PTO" }));
    expect(onOpenSource).toHaveBeenCalledWith(expect.objectContaining({ chunk_id: "c9", document_id: "d9" }));
    expect(screen.queryByRole("button", { name: /Open source/ })).not.toBeInTheDocument();
  });
});
