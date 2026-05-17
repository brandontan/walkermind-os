import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { BottomNav } from "./components/BottomNav";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { AuthContext, useAuth, useAuthState } from "./lib/auth";
import { SSEStatusContext, useSSE } from "./lib/sse";
import { UiModeContext, useUiModeState } from "./lib/uiMode";
import { AuthPage } from "./pages/AuthPage";
import { AutoTradePage } from "./pages/AutoTradePage";
import { CopyTradePage } from "./pages/CopyTradePage";
import { DashboardPage } from "./pages/DashboardPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WalletPage } from "./pages/WalletPage";

function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const isAuth = location.pathname === "/auth";

  // Keep a single SSE connection alive at app level (no-op when token is null).
  const { connected: sseConnected } = useSSE(user?.token ?? null, {});

  const showChrome = Boolean(user) && !isAuth;

  return (
    <SSEStatusContext.Provider value={sseConnected}>
    <div className="min-h-screen text-ink-1 font-sans overflow-hidden">
      {/* Ambient washes — Tactical Terminal v3.2 */}
      <div className="ambient amb-gold" aria-hidden />
      <div className="ambient amb-blue" aria-hidden />

      {/* Desktop sidebar — fixed left, hidden on mobile */}
      {showChrome && <DesktopSidebar />}

      {/* Content: mobile-centered up to 440px; desktop full-width offset from sidebar */}
      <div className="flex justify-center md:block relative" style={{ zIndex: 1 }}>
        <div
          className={[
            "w-full max-w-mobile",
            showChrome ? "md:max-w-none md:ml-[220px] pb-24 md:pb-0" : "",
          ].join(" ")}
        >
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
              path="/copy-trade"
              element={user ? <CopyTradePage /> : <Navigate to="/auth" replace />}
            />
            <Route
              path="/settings"
              element={user ? <SettingsPage /> : <Navigate to="/auth" replace />}
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          {showChrome && <BottomNav />}
        </div>
      </div>
    </div>
    </SSEStatusContext.Provider>
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
