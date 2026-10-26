import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { useWorkspace } from "../auth/WorkspaceContext";
import { useLearningPlans, useRecentReading } from "../api/hooksLearning";
import { Icon } from "../components/Icon";
import { AgentLauncher } from "../components/learn/AgentLauncher";
import { PlanCreateForm } from "../components/learn/PlanCreateForm";
import { PlanView } from "../components/learn/PlanView";
import { ProgressBar } from "../components/learn/ProgressBar";
import { StudySetDetail } from "../components/learn/StudySetDetail";
import { StudySetList } from "../components/learn/StudySetList";
import { Card, Empty, ErrorBanner, Spinner } from "../components/ui";

const TABS = [
  { to: "/learn", label: "Overview", end: true },
  { to: "/learn/sets", label: "Study sets", end: false },
  { to: "/learn/plans", label: "Plans", end: false },
  { to: "/learn/tools", label: "Summarize and compare", end: false },
];

function Overview({ workspaceId }: { workspaceId: string }) {
  const recent = useRecentReading(workspaceId);
  const plans = useLearningPlans(workspaceId);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Continue reading">
        {recent.isLoading && <Spinner label="Loading" />}
        <ErrorBanner error={recent.error} />
        {recent.data && recent.data.length === 0 && <Empty>Documents you open show up here with how far you got.</Empty>}
        <ul className="space-y-3">
          {recent.data?.slice(0, 6).map((item) => (
            <li key={item.document_id}>
              <p className="text-sm font-medium text-slate-900">{item.document_title}</p>
              <p className="mb-1 text-xs text-slate-500">
                {item.last_page ? `Page ${item.last_page}${item.page_count ? ` of ${item.page_count}` : ""} - ` : ""}
                {Math.round(item.percent)}% read
              </p>
              <ProgressBar percent={item.percent} label={`Reading progress in ${item.document_title}`} />
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Your plans" actions={<Link to="/learn/plans" className="text-sm text-indigo-700 hover:underline">New plan</Link>}>
        {plans.isLoading && <Spinner label="Loading" />}
        <ErrorBanner error={plans.error} />
        {plans.data && plans.data.length === 0 && <Empty>No plans yet. Make one from a study set or a topic.</Empty>}
        <PlanList plans={plans.data ?? []} />
      </Card>
      <div className="lg:col-span-2">
        <Card title="Study sets" actions={<Link to="/learn/sets" className="text-sm text-indigo-700 hover:underline">Manage</Link>}>
          <p className="text-sm text-slate-600">
            Keep your own reading lists, track progress across them, then turn one into a plan.{" "}
            <Link to="/learn/sets" className="text-indigo-700 underline">
              Open study sets
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}

function PlanList({ plans }: { plans: { id: string; title: string; steps_done: number; steps_total: number; percent: number }[] }) {
  return (
    <ul className="space-y-3">
      {plans.map((plan) => (
        <li key={plan.id}>
          <Link to={`/learn/plans/${plan.id}`} className="block rounded-xl border border-slate-200 p-3 hover:border-indigo-300">
            <p className="text-sm font-medium text-slate-900">{plan.title}</p>
            <p className="mb-1 text-xs text-slate-500">
              {plan.steps_done} of {plan.steps_total} steps done
            </p>
            <ProgressBar percent={plan.percent} label={`Progress in ${plan.title}`} />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function PlansIndex({ workspaceId }: { workspaceId: string }) {
  const plans = useLearningPlans(workspaceId);
  const navigate = useNavigate();
  return (
    <div className="space-y-4">
      <PlanCreateForm workspaceId={workspaceId} onCreated={(id) => navigate(`/learn/plans/${id}`)} />
      <Card title="Your plans">
        {plans.isLoading && <Spinner label="Loading" />}
        <ErrorBanner error={plans.error} />
        {plans.data && plans.data.length === 0 && <Empty>No plans yet.</Empty>}
        <PlanList plans={plans.data ?? []} />
      </Card>
    </div>
  );
}

function SetRoute() {
  const { id } = useParams();
  return id ? <StudySetDetail setId={id} /> : null;
}

function PlanRoute({ workspaceId }: { workspaceId: string }) {
  const { id } = useParams();
  return id ? <PlanView planId={id} workspaceId={workspaceId} /> : null;
}

export function LearnPage() {
  const { current, loading } = useWorkspace();
  return (
    <div className="space-y-5">
      <header className="flex items-center gap-2">
        <Icon name="learn" className="h-6 w-6 text-indigo-600" />
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Learn</h1>
      </header>
      <nav aria-label="Learn sections" className="flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              `-mb-px border-b-2 px-3 py-2 text-sm font-medium ${isActive ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-600 hover:text-slate-900"}`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      {loading && <Spinner label="Loading workspace" />}
      {!loading && !current && <Empty>Join or create a workspace to start learning.</Empty>}
      {current && (
        <Routes>
          <Route index element={<Overview workspaceId={current.id} />} />
          <Route path="sets" element={<StudySetList workspaceId={current.id} />} />
          <Route path="sets/:id" element={<SetRoute />} />
          <Route path="plans" element={<PlansIndex workspaceId={current.id} />} />
          <Route path="plans/:id" element={<PlanRoute workspaceId={current.id} />} />
          <Route path="tools" element={<AgentLauncher workspaceId={current.id} />} />
          <Route path="*" element={<Empty>That page does not exist.</Empty>} />
        </Routes>
      )}
    </div>
  );
}
