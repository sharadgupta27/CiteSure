import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState, type FormEvent } from "react";
import { ApiError, type Answer, type AskScope, type Citation } from "../api/client";
import { keys, usePublicResearchStatus, useThread, useThreads } from "../api/hooks";
import { streamAsk } from "../api/stream";
import { useWorkspace } from "../auth/WorkspaceContext";
import { AnswerView } from "../components/AnswerView";
import { FeedbackBar } from "../components/FeedbackBar";
import { ScopePicker } from "../components/ScopePicker";
import { SourceViewer } from "../components/SourceViewer";
import { Button, Card, Empty, ErrorBanner, Spinner, inputClass } from "../components/ui";
import { STAGE_LABELS, initialStreamState, streamReducer } from "../lib/streamReducer";

interface Turn {
  question: string;
  answer: Answer;
}

const EXAMPLES = ["How many weeks of paid parental leave do primary caregivers get?", "How quickly must I report a phishing email?", "What is the nightly hotel limit in major cities?"];

export function AskPage() {
  const { current } = useWorkspace();
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [stream, dispatch] = useReducer(streamReducer, initialStreamState);
  const [source, setSource] = useState<Citation | null>(null);
  const [scope, setScope] = useState<AskScope>("internal");
  const [publicQuery, setPublicQuery] = useState<string | null>(null);
  const researchStatus = usePublicResearchStatus();
  const publicResearch = researchStatus.data?.enabled ? researchStatus.data : null;
  const abort = useRef<AbortController | null>(null);

  const threads = useThreads(current?.id);
  const [openThread, setOpenThread] = useState<string | undefined>();
  const history = useThread(openThread);

  useEffect(() => {
    if (history.data) {
      setTurns(history.data.answers.map((a) => ({ question: a.question, answer: a })));
      setThreadId(history.data.id);
      dispatch({ type: "reset" });
    }
  }, [history.data]);

  useEffect(() => () => abort.current?.abort(), []);

  const ask = useCallback(
    async (text: string) => {
      if (!current || text.trim().length < 3) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setAsked(text);
      setQuestion("");
      setPublicQuery(null);
      dispatch({ type: "start" });
      try {
        await streamAsk(
          {
            workspace_id: current.id,
            question: text.trim(),
            thread_id: threadId,
            // Only a server with the public lane switched on ever sees a scope other than "internal".
            ...(publicResearch && scope !== "internal" ? { scope, public_query: publicQuery } : {}),
          },
          { onMessage: (message) => dispatch({ type: "message", message }) },
          controller.signal,
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        dispatch({ type: "failed", error: error instanceof ApiError ? error.message : "The connection was interrupted. Please try again." });
      }
    },
    [current, threadId, publicResearch, scope, publicQuery],
  );

  // When the stream finishes, move the answer into the conversation and refresh the history list.
  useEffect(() => {
    if (stream.phase === "done" && stream.answer) {
      const answer = stream.answer;
      setTurns((previous) => [...previous, { question: asked, answer }]);
      setThreadId(answer.thread_id);
      dispatch({ type: "reset" });
      if (current) void queryClient.invalidateQueries({ queryKey: keys.threads(current.id) });
    }
  }, [stream.phase, stream.answer, asked, current, queryClient]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question);
  }

  function newConversation() {
    abort.current?.abort();
    setTurns([]);
    setThreadId(null);
    setOpenThread(undefined);
    dispatch({ type: "reset" });
  }

  const busy = stream.phase === "streaming";

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
      <div className="space-y-4">
        <form onSubmit={submit} className="flex gap-2">
          <input
            aria-label="Your question"
            className={inputClass}
            placeholder="Ask a question about your documents…"
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value);
              setPublicQuery(null); // an approved query belongs to the question it was checked for
            }}
            disabled={busy}
          />
          <Button type="submit" disabled={busy || question.trim().length < 3}>
            Ask
          </Button>
        </form>

        {publicResearch && (
          <ScopePicker
            status={publicResearch}
            scope={scope}
            onScope={setScope}
            question={question}
            publicQuery={publicQuery}
            onPublicQuery={setPublicQuery}
          />
        )}

        {turns.length === 0 && !busy && (
          <Card title="Try asking">
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <Button key={example} variant="secondary" onClick={() => void ask(example)}>
                  {example}
                </Button>
              ))}
            </div>
          </Card>
        )}

        {turns.map((turn, index) => (
          <Card key={turn.answer.id}>
            <h3 className="mb-2 font-semibold text-slate-900">{turn.question}</h3>
            <AnswerView answer={turn.answer} onOpenSource={setSource} />
            {index === turns.length - 1 && (
              <div className="mt-3 border-t border-slate-100 pt-3">
                <FeedbackBar answerId={turn.answer.id} />
              </div>
            )}
          </Card>
        ))}

        {(busy || stream.phase === "error") && (
          <Card>
            <h3 className="mb-2 font-semibold text-slate-900">{asked}</h3>
            {busy && <Spinner label={STAGE_LABELS[stream.stage ?? "retrieving"] ?? "Working…"} />}
            {busy && stream.text && <p className="mt-2 leading-7 text-slate-700">{stream.text}</p>}
            {stream.phase === "error" && <ErrorBanner error={new Error(stream.error ?? "Something went wrong")} />}
          </Card>
        )}
      </div>

      <aside className="space-y-2" aria-label="History">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">History</h2>
          <Button variant="ghost" onClick={newConversation}>
            New
          </Button>
        </div>
        {threads.isLoading && <Spinner />}
        {threads.data && threads.data.length === 0 && <Empty>No questions yet.</Empty>}
        <ul className="space-y-1">
          {threads.data?.map((thread) => (
            <li key={thread.id}>
              <button
                type="button"
                onClick={() => setOpenThread(thread.id)}
                className={`w-full truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-100 ${threadId === thread.id ? "bg-indigo-50 text-indigo-700" : "text-slate-700"}`}
              >
                {thread.title}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <SourceViewer citation={source} onClose={() => setSource(null)} />
    </div>
  );
}
