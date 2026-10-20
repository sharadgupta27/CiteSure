import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { WorkspaceProvider, useWorkspace } from "./auth/WorkspaceContext";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { AskPage } from "./pages/AskPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { FeedbackPage } from "./pages/FeedbackPage";
import { LoginPage } from "./pages/LoginPage";
import { QualityPage } from "./pages/QualityPage";
import { WorkspacePage } from "./pages/WorkspacePage";

function AdminOnly({ children }: { children: JSX.Element }) {
  const { isAdmin, loading } = useWorkspace();
  if (loading) return <Spinner />;
  return isAdmin ? children : <Navigate to="/ask" replace />;
}

export function App() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="grid min-h-full place-items-center">
        <Spinner label="Signing you in…" />
      </div>
    );
  }
  if (!user) return <LoginPage />;
  return (
    <WorkspaceProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/ask" element={<AskPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/workspace" element={<AdminOnly><WorkspacePage /></AdminOnly>} />
          <Route path="/feedback" element={<AdminOnly><FeedbackPage /></AdminOnly>} />
          <Route path="/quality" element={<AdminOnly><QualityPage /></AdminOnly>} />
          <Route path="*" element={<Navigate to="/ask" replace />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  );
}
