import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReadingProgress } from "./ReadingProgress";

const mutate = vi.fn();
const reset = vi.fn();
const progress = {
  document_id: "d1",
  last_page: 2,
  pages_read: [1],
  percent: 25,
  last_opened_at: "2026-10-25T10:00:00Z",
  updated_at: "2026-10-25T10:00:00Z",
};
const readingHook = vi.fn();

vi.mock("../api/hooksLearning", () => ({
  useReadingProgress: (id: string | undefined) => readingHook(id),
  useUpdateReadingProgress: () => ({ mutate, isPending: false }),
  useResetReadingProgress: () => ({ mutate: reset }),
}));

beforeEach(() => {
  vi.useFakeTimers();
  mutate.mockClear();
  reset.mockClear();
  readingHook.mockReturnValue({ data: progress, isLoading: false, error: null });
});
afterEach(() => vi.useRealTimers());

describe("ReadingProgress", () => {
  it("shows page and percent with an accessible progress bar", () => {
    render(<ReadingProgress documentId="d1" page={2} pageCount={8} />);
    expect(screen.getByText("Page 2 of 8 - 25% read")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Reading progress" })).toHaveAttribute("aria-valuenow", "25");
  });

  it("reports the page, then marks it read once after the dwell time", () => {
    render(<ReadingProgress documentId="d1" page={3} pageCount={8} dwellMs={1000} />);
    act(() => void vi.advanceTimersByTime(500));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate).toHaveBeenLastCalledWith({ page: 3 });
    act(() => void vi.advanceTimersByTime(600));
    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate).toHaveBeenLastCalledWith({ page: 3, mark_read: true });
    act(() => void vi.advanceTimersByTime(10_000));
    expect(mutate).toHaveBeenCalledTimes(2);
  });

  it("does not mark a page read if the reader moved on before the dwell time", () => {
    const { rerender } = render(<ReadingProgress documentId="d1" page={3} pageCount={8} dwellMs={1000} />);
    act(() => void vi.advanceTimersByTime(600));
    rerender(<ReadingProgress documentId="d1" page={4} pageCount={8} dwellMs={1000} />);
    act(() => void vi.advanceTimersByTime(1100));
    const markedPages = mutate.mock.calls.filter(([body]) => body.mark_read).map(([body]) => body.page);
    expect(markedPages).toEqual([4]);
  });

  it("calls nothing and renders nothing without a document id", () => {
    const { container } = render(<ReadingProgress documentId="" page={1} pageCount={3} />);
    act(() => void vi.advanceTimersByTime(10_000));
    expect(mutate).not.toHaveBeenCalled();
    expect(readingHook).toHaveBeenCalledWith(undefined);
    expect(container).toBeEmptyDOMElement();
  });

  it("marks the page read and resets on request", async () => {
    vi.useRealTimers();
    render(<ReadingProgress documentId="d1" page={5} pageCount={8} dwellMs={60_000} />);
    await userEvent.click(screen.getByRole("button", { name: "Mark page as read" }));
    expect(mutate).toHaveBeenCalledWith({ page: 5, mark_read: true });
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(reset).toHaveBeenCalled();
  });
});
