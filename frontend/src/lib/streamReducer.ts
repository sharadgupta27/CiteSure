import type { Answer } from "../api/client";
import type { StreamMessage } from "../api/stream";

export type Phase = "idle" | "streaming" | "done" | "error";

export interface StreamState {
  phase: Phase;
  /** Last pipeline stage reported by the server: retrieving, researching, generating or verifying. */
  stage: string | null;
  /** Verified answer text streamed so far (never contains unverified claims). */
  text: string;
  answer: Answer | null;
  error: string | null;
}

export const initialStreamState: StreamState = { phase: "idle", stage: null, text: "", answer: null, error: null };

export type StreamAction = { type: "start" } | { type: "reset" } | { type: "message"; message: StreamMessage } | { type: "failed"; error: string };

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  switch (action.type) {
    case "start":
      return { ...initialStreamState, phase: "streaming" };
    case "reset":
      return initialStreamState;
    case "failed":
      return { ...state, phase: "error", error: action.error };
    case "message": {
      const { message } = action;
      if (state.phase !== "streaming") return state; // late events after an abort or an error are ignored
      switch (message.event) {
        case "stage":
          return { ...state, stage: message.data };
        case "token":
          return { ...state, text: state.text + message.data };
        case "final":
          return { ...state, phase: "done", stage: null, answer: message.data };
        case "error":
          return { ...state, phase: "error", stage: null, error: message.data.detail };
      }
    }
  }
}

export const STAGE_LABELS: Record<string, string> = {
  retrieving: "Searching the documents you can access…",
  researching: "Searching published papers and the web…",
  generating: "Writing an answer from the sources…",
  verifying: "Checking every citation against its source…",
};
