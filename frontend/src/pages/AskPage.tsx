import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, type Answer, type AskScope, type Citation } from "../api/client";
import { keys, usePublicResearchStatus, useThread, useThreads } from "../api/hooks";
import { streamAsk } from "../api/stream";
import { useWorkspace } from "../auth/WorkspaceContext";
import { AnswerView } from "../components/AnswerView";
import { FeedbackBar } from "../components/FeedbackBar";
import { Icon, Logo, type IconName } from "../components/Icon";
import { ScopePicker } from "../components/ScopePicker";
import { SourceViewer } from "../components/SourceViewer";
import { Button, Empty, ErrorBanner, Spinner } from "../components/ui";
import { STAGE_LABELS, initialStreamState, streamReducer } from "../lib/streamReducer";

interface Turn {
  question: string;
  answer: Answer;
}

const EXAMPLES = ["How many weeks of paid parental leave do primary caregivers get?", "How quickly must I report a phishing email?", "What is the nightly hotel limit in major cities?"];

const STEPS: { icon: IconName; title: string; body: string }[] = [
  { icon: "search", title: "Retrieve", body: "Searches only the documents you are allowed to read." },
  { icon: "quote", title: "Cite", body: "Each sentence links to the exact passage behind it." },
  { icon: "shield", title: "Verify", body: "Statements the sources do not support are dropped, not guessed." },
];

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

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter adds a line. Never send while an IME is still composing a character.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void ask(question);
    }
  }

  function newConversation() {
    abort.current?.abort();
    setTurns([]);
    setThreadId(null);
    setOpenThread(undefined);
    dispatch({ type: "reset" });
  }

  const busy = stream.phase === "streaming";
  const inConversation = turns.length > 0 || busy || stream.phase === "error";
  const loadingThread = Boolean(openThread) && history.isFetching && turns.length === 0;

  const composer = (
    <form
      onSubmit={submit}
      className="rounded-3xl border border-slate-200 bg-white text-left shadow-glow transition-shadow focus-within:border-indigo-300 focus-within:ring-4 focus-within:ring-indigo-500/10"
    >
      <textarea
        aria-label="Your question"
        rows={inConversation ? 1 : 3}
        className="block w-full resize-none rounded-t-3xl bg-transparent px-5 pt-4 text-base text-slate-900 placeholder:text-slate-400 focus:outline-none"
        placeholder={inConversation ? "Ask a follow-up…" : "Ask a question about your documents…"}
        value={question}
        onChange={(e) => {
          setQuestion(e.target.value);
          setPublicQuery(null); // an approved query belongs to the question it was checked for
        }}
        onKeyDown={onKeyDown}
        disabled={busy}
      />
      {publicResearch && (
        <div className="px-4 pb-1 pt-1">
          <ScopePicker
            status={publicResearch}
            scope={scope}
            onScope={setScope}
            question={question}
            publicQuery={publicQuery}
            onPublicQuery={setPublicQuery}
          />
        </div>
      )}
      <div className="flex items-center justify-between gap-3 px-3 pb-3 pt-1">
        <span className="inline-flex min-w-0 items-center gap-1.5 truncate rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">
          <Icon name="lock" className="h-3.5 w-3.5 text-slate-500" />
          <span className="truncate">{current?.name ?? "Your workspace"}</span>
          <span className="hidden text-slate-400 sm:inline">· only what you may read</span>
        </span>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-slate-400 md:inline">Enter to send</span>
          <Button type="submit" disabled={busy || question.trim().length < 3} className="rounded-full px-4">
            Ask
            <Icon name="arrow" className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </form>
  );

  if (!inConversation) {
    const recent = threads.data?.slice(0, 6) ?? [];
    return (
      <div className="relative isolate -mx-4 -mt-6 px-4 pb-10 pt-12 sm:-mx-8 sm:-mt-8 sm:px-8 sm:pt-20">
        <div className="aurora absolute inset-0 -z-10 rounded-b-[3rem]" aria-hidden="true" />
        <div className="dot-grid absolute inset-0 -z-10" aria-hidden="true" />

        <div className="mx-auto max-w-3xl animate-rise text-center">
          <div className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-white/80 px-3 py-1 text-xs font-medium text-indigo-700 shadow-sm backdrop-blur">
            <Icon name="shield" className="h-3.5 w-3.5" />
            Verified answers from your own documents
          </div>
          <div className="mb-4 flex items-center justify-center gap-3">
            <Logo className="h-11 w-11" />
            <span className="text-3xl font-bold tracking-tight text-slate-900">CiteSure</span>
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
            Answers you can <span className="text-gradient">verify</span>
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-base text-slate-600">
            Ask in plain language. Every sentence links back to the exact passage it came from, or you get an honest &ldquo;I don&rsquo;t know&rdquo;.
          </p>

          <div className="mt-8">{composer}</div>

          {loadingThread && (
            <div className="mt-4">
              <Spinner label="Opening conversation…" />
            </div>
          )}

          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => void ask(example)}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/90 px-3.5 py-2 text-left text-sm text-slate-700 shadow-sm transition-colors hover:border-indigo-300 hover:bg-indigo-50/60 hover:text-indigo-800"
              >
                <Icon name="sparkle" className="h-3.5 w-3.5 text-indigo-500" />
                {example}
              </button>
            ))}
          </div>
        </div>

        <div className="mx-auto mt-14 grid max-w-5xl gap-4 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <div key={step.title} className="rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-soft backdrop-blur">
              <div className="mb-3 flex items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
                  <Icon name={step.icon} className="h-5 w-5" />
                </span>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Step {index + 1}</span>
              </div>
              <h2 className="text-base font-semibold text-slate-900">{step.title}</h2>
              <p className="mt-1 text-sm text-slate-600">{step.body}</p>
            </div>
          ))}
        </div>

        <div className="mx-auto mt-6 grid max-w-5xl gap-4 md:grid-cols-[1fr_1.4fr]">
          <Link
            to="/documents"
            aria-label="Open library"
            className="group flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-indigo-200 bg-indigo-50/40 p-6 text-center transition-colors hover:border-indigo-400 hover:bg-indigo-50"
          >
            <span className="mb-3 grid h-11 w-11 place-items-center rounded-full bg-white text-indigo-600 shadow-sm">
              <Icon name="upload" className="h-5 w-5" />
            </span>
            <span className="font-semibold text-slate-900">Your library</span>
            <span className="mt-1 text-sm text-slate-600">PDF, DOCX, Markdown, HTML or text. Indexed and ready to cite.</span>
            <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-700 group-hover:underline">
              Open library <Icon name="arrow" className="h-3.5 w-3.5" />
            </span>
          </Link>

          <section className="rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-soft backdrop-blur" aria-label="Recent threads">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Icon name="clock" className="h-4 w-4 text-slate-400" />
              Recent threads
            </h2>
            {threads.isLoading && <Spinner />}
            {threads.data && recent.length === 0 && <p className="text-sm text-slate-500">No questions yet. Your conversations will show up here.</p>}
            <ul className="space-y-1">
              {recent.map((thread) => (
                <li key={thread.id}>
                  <button
                    type="button"
                    onClick={() => setOpenThread(thread.id)}
                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-slate-700 transition-colors hover:bg-indigo-50 hover:text-indigo-800"
                  >
                    <Icon name="ask" className="h-4 w-4 text-slate-400" />
                    <span className="truncate">{thread.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <SourceViewer citation={source} onClose={() => setSource(null)} />
      </div>
    );
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[1fr_16rem]">
      <div className="min-w-0 space-y-5">
        {turns.map((turn, index) => (
          <article key={turn.answer.id} className="animate-rise space-y-3">
            <h3 className="text-xl font-semibold tracking-tight text-slate-900">{turn.question}</h3>
            <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-soft">
              <p className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-indigo-600">
                <Logo className="h-5 w-5" />
                CiteSure
              </p>
              <AnswerView answer={turn.answer} onOpenSource={setSource} />
              {index === turns.length - 1 && (
                <div className="mt-4 border-t border-slate-100 pt-3">
                  <FeedbackBar answerId={turn.answer.id} />
                </div>
              )}
            </div>
          </article>
        ))}

        {(busy || stream.phase === "error") && (
          <article className="space-y-3">
            <h3 className="text-xl font-semibold tracking-tight text-slate-900">{asked}</h3>
            <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-soft">
              {busy && <Spinner label={STAGE_LABELS[stream.stage ?? "retrieving"] ?? "Working…"} />}
              {busy && stream.text && <p className="mt-2 leading-7 text-slate-700">{stream.text}</p>}
              {stream.phase === "error" && <ErrorBanner error={new Error(stream.error ?? "Something went wrong")} />}
            </div>
          </article>
        )}

        <div className="sticky bottom-4 z-10 pt-2">{composer}</div>
      </div>

      <aside className="space-y-2 lg:pt-1" aria-label="History">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">History</h2>
          <Button variant="ghost" onClick={newConversation} className="px-2! py-1!">
            <Icon name="plus" className="h-3.5 w-3.5" />
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
                className={`w-full truncate rounded-xl px-3 py-2 text-left text-sm transition-colors hover:bg-slate-100 ${threadId === thread.id ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-700"}`}
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
