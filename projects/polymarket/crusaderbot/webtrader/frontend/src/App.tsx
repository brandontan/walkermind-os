import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { BottomNav } from "./components/BottomNav";
import { AuthContext, useAuth, useAuthState } from "./lib/auth";
import { useSSE } from "./lib/sse";
import { UiModeContext, useUiModeState } from "./lib/uiMode";
import { AuthPage } from "./pages/AuthPage";
import { AutoTradePage } from "./pages/AutoTradePage";
import { DashboardPage } from "./pages/DashboardPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WalletPage } from "./pages/WalletPage";

function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const isAuth = location.pathname === "/auth";

  // Keep a single SSE connection alive at app level (no-op when token is null).
  useSSE(user?.token ?? null, {});

  return (
    <div className="min-h-screen text-ink-1 font-sans flex justify-center overflow-hidden">
      {/* Ambient washes — Tactical Terminal v3.2 */}
      <div className="ambient amb-gold" aria-hidden />
      <div className="ambient amb-blue" aria-hidden />

      <div className="w-full max-w-mobile relative" style={{ zIndex: 1, paddingBottom: "96px" }}>
        <Routes>
          <Route path="/" element={<Navigate to={user ? "/dashboard" : "/auth"} replace />} />
          <Route path="/auth" element={<AuthPage />} />
          <Route
            path="/dashboard"
            element={user ? <DashboardPage /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/autotrade"
            element={user ? <AutoTradePage /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/portfolio"
            element={user ? <PortfolioPage /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/wallet"
            element={user ? <WalletPage /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/settings"
            element={user ? <SettingsPage /> : <Navigate to="/auth" replace />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        {user && !isAuth && <BottomNav />}
      </div>
    </div>
  );
}

export function App() {
  const authState = useAuthState();
  const uiMode = useUiModeState();

  return (
    <AuthContext.Provider value={authState}>
      <UiModeContext.Provider value={uiMode}>
        <BrowserRouter basename="/dashboard">
          <AppShell />
        </BrowserRouter>
      </UiModeContext.Provider>
    </AuthContext.Provider>
  );
}
