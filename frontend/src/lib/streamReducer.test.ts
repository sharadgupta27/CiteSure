import { answer } from "../test/factories";
import { initialStreamState, streamReducer, type StreamState } from "./streamReducer";

const started = (): StreamState => streamReducer(initialStreamState, { type: "start" });

describe("streamReducer", () => {
  it("starts streaming from a clean state", () => {
    const state = streamReducer({ ...initialStreamState, text: "old", phase: "done" }, { type: "start" });
    expect(state).toEqual({ phase: "streaming", stage: null, text: "", answer: null, error: null });
  });

  it("follows the stage events", () => {
    let state = started();
    for (const stage of ["retrieving", "generating", "verifying"]) {
      state = streamReducer(state, { type: "message", message: { event: "stage", data: stage } });
      expect(state.stage).toBe(stage);
    }
  });

  it("appends token events in order", () => {
    let state = started();
    for (const piece of ["Primary ", "caregivers ", "get 16 weeks. "]) {
      state = streamReducer(state, { type: "message", message: { event: "token", data: piece } });
    }
    expect(state.text).toBe("Primary caregivers get 16 weeks. ");
  });

  it("finishes with the final answer", () => {
    const final = answer();
    const state = streamReducer(started(), { type: "message", message: { event: "final", data: final } });
    expect(state.phase).toBe("done");
    expect(state.answer).toBe(final);
    expect(state.stage).toBeNull();
  });

  it("turns a server error event into an error state", () => {
    const state = streamReducer(started(), { type: "message", message: { event: "error", data: { code: "upstream_error", detail: "Model unavailable" } } });
    expect(state).toMatchObject({ phase: "error", error: "Model unavailable" });
  });

  it("ignores events that arrive after the stream ended or was reset", () => {
    const done = streamReducer(started(), { type: "message", message: { event: "final", data: answer() } });
    expect(streamReducer(done, { type: "message", message: { event: "token", data: "late" } })).toBe(done);
    expect(streamReducer(initialStreamState, { type: "message", message: { event: "stage", data: "retrieving" } })).toBe(initialStreamState);
  });

  it("records a network failure", () => {
    expect(streamReducer(started(), { type: "failed", error: "offline" })).toMatchObject({ phase: "error", error: "offline" });
  });

  it("resets", () => {
    expect(streamReducer(started(), { type: "reset" })).toBe(initialStreamState);
  });
});
