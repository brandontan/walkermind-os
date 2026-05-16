import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { BottomNav } from "./components/BottomNav";
import { AuthContext, useAuth, useAuthState } from "./lib/auth";
import { useSSE } from "./lib/sse";
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

  // Keep a single SSE connection alive at app level (no-op when token is null)
  useSSE(user?.token ?? null, {});

  return (
    <div className="min-h-screen bg-bg text-primary font-sans flex justify-center overflow-hidden">
      {/* Ambient background gradients — fixed, pointer-events-none */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{ zIndex: 0 }}
        aria-hidden="true"
      >
        <div
          className="absolute"
          style={{
            width: "500px",
            height: "500px",
            top: "-120px",
            left: "-120px",
            background: "radial-gradient(ellipse at center, rgba(245,200,66,0.05) 0%, transparent 70%)",
          }}
        />
        <div
          className="absolute"
          style={{
            width: "500px",
            height: "500px",
            bottom: "-120px",
            right: "-120px",
            background: "radial-gradient(ellipse at center, rgba(77,158,255,0.05) 0%, transparent 70%)",
          }}
        />
      </div>
      <div className="w-full max-w-mobile relative" style={{ zIndex: 1 }}>
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

  return (
    <AuthContext.Provider value={authState}>
      <BrowserRouter basename="/dashboard">
        <AppShell />
      </BrowserRouter>
    </AuthContext.Provider>
  );
}
