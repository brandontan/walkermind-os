import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AlertCenter } from "./components/AlertCenter";
import { BottomNav } from "./components/BottomNav";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { AuthContext, useAuth, useAuthState } from "./lib/auth";
import { SSEStatusContext, useSSE } from "./lib/sse";
import { UiModeContext, useUiModeState } from "./lib/uiMode";
import { makeApi, type AlertItem } from "./lib/api";
import { AuthPage } from "./pages/AuthPage";
import { AutoTradePage } from "./pages/AutoTradePage";
import { CopyTradePage } from "./pages/CopyTradePage";
import { DashboardPage } from "./pages/DashboardPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WalletPage } from "./pages/WalletPage";

const LAST_SEEN_KEY = "alertCenter_lastSeen";

interface AlertCenterCtx {
  alerts: AlertItem[];
  unreadCount: number;
  isOpen: boolean;
  openAlertCenter: () => void;
  closeAlertCenter: () => void;
}

export const AlertCenterContext = createContext<AlertCenterCtx>({
  alerts: [],
  unreadCount: 0,
  isOpen: false,
  openAlertCenter: () => undefined,
  closeAlertCenter: () => undefined,
});

export function useAlertCenter(): AlertCenterCtx {
  return useContext(AlertCenterContext);
}

function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const isAuth = location.pathname === "/auth";
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);

  const showChrome = Boolean(user) && !isAuth;

  // ── Alert Center global state ────────────────────────────────────────────
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [isAlertOpen, setIsAlertOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<number>(() => {
    const stored = localStorage.getItem(LAST_SEEN_KEY);
    return stored ? Number(stored) : 0;
  });

  const fetchAlerts = useCallback(async () => {
    if (!user) return;
    try {
      const data = await api.getAlerts();
      setAlerts(data);
    } catch {
      // non-critical — panel shows empty state
    }
  }, [api, user]);

  // SSE connection — fetchAlerts defined above so it's safe to reference here.
  // Re-fetch on both system and alert events to keep the Alert Center in sync.
  const { connected: sseConnected } = useSSE(user?.token ?? null, {
    system: fetchAlerts,
    alert: fetchAlerts,
  });

  useEffect(() => {
    void fetchAlerts();
  }, [fetchAlerts]);

  const unreadCount = useMemo(
    () => alerts.filter((a) => new Date(a.created_at).getTime() > lastSeen).length,
    [alerts, lastSeen],
  );

  const openAlertCenter = useCallback(() => {
    setIsAlertOpen(true);
    const now = Date.now();
    setLastSeen(now);
    localStorage.setItem(LAST_SEEN_KEY, String(now));
  }, []);

  const closeAlertCenter = useCallback(() => setIsAlertOpen(false), []);

  const alertCtx: AlertCenterCtx = useMemo(
    () => ({ alerts, unreadCount, isOpen: isAlertOpen, openAlertCenter, closeAlertCenter }),
    [alerts, unreadCount, isAlertOpen, openAlertCenter, closeAlertCenter],
  );

  return (
    <AlertCenterContext.Provider value={alertCtx}>
    <SSEStatusContext.Provider value={sseConnected}>
    <div className="min-h-screen text-ink-1 font-sans overflow-hidden">
      {/* Ambient washes — Tactical Terminal v3.2 */}
      <div className="ambient amb-gold" aria-hidden />
      <div className="ambient amb-blue" aria-hidden />

      {/* Desktop sidebar — fixed left, hidden on mobile */}
      {showChrome && <DesktopSidebar />}

      {/* Content: mobile-centered up to 440px; desktop full-width offset from sidebar */}
      <div
        className={[
          "relative",
          showChrome ? "flex justify-center md:block" : "flex justify-center",
        ].join(" ")}
        style={{ zIndex: 1 }}
      >
        <div
          className={[
            "w-full",
            showChrome
              ? "max-w-mobile md:max-w-none md:ml-[180px] lg:ml-[220px] md:overflow-x-hidden pb-24 md:pb-0"
              : "max-w-mobile md:max-w-none",
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

      {/* Alert Center — rendered at root so it overlays all pages */}
      <AlertCenter
        isOpen={isAlertOpen}
        alerts={alerts}
        onClose={closeAlertCenter}
      />
    </div>
    </SSEStatusContext.Provider>
    </AlertCenterContext.Provider>
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
