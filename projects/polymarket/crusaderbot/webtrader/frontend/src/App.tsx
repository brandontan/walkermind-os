import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AlertCenter } from "./components/AlertCenter";
import { BottomNav } from "./components/BottomNav";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { AuthContext, useAuth, useAuthState } from "./lib/auth";
import { SSEStatusContext, useSSE } from "./lib/sse";
import { UiModeContext, useUiModeState } from "./lib/uiMode";
import { makeApi, setUnauthorizedHandler, type AlertItem } from "./lib/api";
import { AuthPage } from "./pages/AuthPage";
import { AutoTradePage } from "./pages/AutoTradePage";
import { DashboardPage } from "./pages/DashboardPage";
import { DiscoverPage } from "./pages/DiscoverPage";
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

interface ScannerCtx {
  lastScanMs: number | null;
}

export const ScannerContext = createContext<ScannerCtx>({ lastScanMs: null });

export function useScannerStatus(): ScannerCtx {
  return useContext(ScannerContext);
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
      const [sysResult, posResult] = await Promise.allSettled([
        api.getAlerts(),
        api.getPositions("closed", 10, 0),
      ]);
      const sysAlerts: AlertItem[] = sysResult.status === "fulfilled" ? sysResult.value : [];
      const closed = posResult.status === "fulfilled" ? posResult.value : [];

      // Synthesize trade alerts from recent closed positions when system_alerts is empty
      const tradeAlerts: AlertItem[] = closed
        .filter((p) => p.closed_at)
        .map((p) => {
          const pnl = p.pnl_usdc ?? 0;
          const won = pnl >= 0;
          return {
            id: `pos-${p.id}`,
            severity: "trade",
            title: won
              ? `✓ Trade Closed  +$${pnl.toFixed(2)}`
              : `Trade Closed  −$${Math.abs(pnl).toFixed(2)}`,
            body: p.market_question ?? null,
            created_at: p.closed_at!,
          };
        });

      const seen = new Set(sysAlerts.map((a) => a.id));
      const merged = [...sysAlerts, ...tradeAlerts.filter((a) => !seen.has(a.id))];
      setAlerts(merged);
    } catch {
      // non-critical — panel shows empty state
    }
  }, [api, user]);

  const [lastScanMs, setLastScanMs] = useState<number | null>(null);

  // SSE connection — fetchAlerts defined above so it's safe to reference here.
  // Re-fetch on both system and alert events to keep the Alert Center in sync.
  const { connected: sseConnected } = useSSE(user?.token ?? null, {
    system: fetchAlerts,
    alert: fetchAlerts,
    scanner_tick: (raw) => {
      const payload = raw as { ts?: number };
      if (payload.ts) setLastScanMs(payload.ts * 1000);
    },
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
    <ScannerContext.Provider value={{ lastScanMs }}>
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
              element={<Navigate to="/autotrade?tab=copy" replace />}
            />
            <Route
              path="/discover"
              element={user ? <DiscoverPage /> : <Navigate to="/auth" replace />}
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
    </ScannerContext.Provider>
  );
}

export function App() {
  const authState = useAuthState();
  const uiMode = useUiModeState();

  // Wire the global 401 handler so any expired-token API response triggers
  // logout + redirect to login without requiring a manual page refresh.
  useEffect(() => {
    setUnauthorizedHandler(authState.logout);
  }, [authState.logout]);

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
