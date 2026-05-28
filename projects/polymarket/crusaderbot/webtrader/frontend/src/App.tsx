import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AlertCenter } from "./components/AlertCenter";
import { BottomNav } from "./components/BottomNav";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { AuthContext, useAuth, useAuthState } from "./lib/auth";
import { SSEStatusContext, useSSE } from "./lib/sse";
import { UiModeContext, useUiModeState } from "./lib/uiMode";
import { makeApi, setUnauthorizedHandler, type AlertItem } from "./lib/api";
// Critical path — keep eager
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
// Heavy pages — lazy-loaded on first navigation
const AutoTradePage  = lazy(() => import("./pages/AutoTradePage").then(m => ({ default: m.AutoTradePage })));
const DiscoverPage   = lazy(() => import("./pages/DiscoverPage").then(m => ({ default: m.DiscoverPage })));
const PortfolioPage  = lazy(() => import("./pages/PortfolioPage").then(m => ({ default: m.PortfolioPage })));
const SettingsPage   = lazy(() => import("./pages/SettingsPage").then(m => ({ default: m.SettingsPage })));
const WalletPage     = lazy(() => import("./pages/WalletPage").then(m => ({ default: m.WalletPage })));

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[40vh]">
      <span className="w-5 h-5 rounded-full border-2 border-ink-4 border-t-grn animate-spin" />
    </div>
  );
}

const LAST_SEEN_KEY = "alertCenter_lastSeen";
const DISMISSED_KEY = "alertCenter_dismissed";
const DISMISSED_CAP = 500;

function loadDismissed(): Set<string> {
  try {
    const stored = localStorage.getItem(DISMISSED_KEY);
    return stored ? new Set<string>(JSON.parse(stored) as string[]) : new Set<string>();
  } catch {
    return new Set<string>();
  }
}

interface AlertCenterCtx {
  alerts: AlertItem[];
  unreadCount: number;
  isOpen: boolean;
  openAlertCenter: () => void;
  closeAlertCenter: () => void;
  dismissAlert: (id: string) => void;
  markAllRead: () => void;
  loadMoreAlerts: () => Promise<void>;
  hasMoreAlerts: boolean;
}

export const AlertCenterContext = createContext<AlertCenterCtx>({
  alerts: [],
  unreadCount: 0,
  isOpen: false,
  openAlertCenter: () => undefined,
  closeAlertCenter: () => undefined,
  dismissAlert: () => undefined,
  markAllRead: () => undefined,
  loadMoreAlerts: async () => undefined,
  hasMoreAlerts: false,
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
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed);
  const [alertOffset, setAlertOffset] = useState(0);
  const [hasMoreAlerts, setHasMoreAlerts] = useState(false);
  const ALERT_PAGE = 10;
  const [isAlertOpen, setIsAlertOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<number>(() => {
    const stored = localStorage.getItem(LAST_SEEN_KEY);
    return stored ? Number(stored) : 0;
  });

  const fetchAlerts = useCallback(async (offset = 0, append = false) => {
    if (!user) return;
    try {
      const [sysResult, posResult] = await Promise.allSettled([
        offset === 0 ? api.getAlerts() : Promise.resolve([] as AlertItem[]),
        api.getPositions("closed", ALERT_PAGE + 1, offset),
      ]);
      const sysAlerts: AlertItem[] = sysResult.status === "fulfilled" ? sysResult.value : [];
      const closedRaw = posResult.status === "fulfilled" ? posResult.value : [];
      const hasMore = closedRaw.length > ALERT_PAGE;
      const closed = closedRaw.slice(0, ALERT_PAGE);

      const tradeAlerts: AlertItem[] = closed
        .filter((p) => p.closed_at)
        .map((p) => {
          const pnl = p.pnl_usdc ?? 0;
          const won = pnl >= 0;
          return {
            id: `pos-${p.id}`,
            severity: "trade",
            title: won
              ? `Trade Closed  +$${pnl.toFixed(2)}`
              : `Trade Closed  −$${Math.abs(pnl).toFixed(2)}`,
            body: p.market_question ?? null,
            created_at: p.closed_at!,
          };
        });

      const seen = new Set(sysAlerts.map((a) => a.id));
      const newItems = [...(offset === 0 ? sysAlerts : []), ...tradeAlerts.filter((a) => !seen.has(a.id))];
      setAlerts(prev => append ? [...prev, ...newItems] : newItems);
      setHasMoreAlerts(hasMore);
    } catch {
      // non-critical — panel shows empty state
    }
  }, [api, user]);

  const loadMoreAlerts = useCallback(async () => {
    const next = alertOffset + ALERT_PAGE;
    setAlertOffset(next);
    await fetchAlerts(next, true);
  }, [alertOffset, fetchAlerts]);

  const dismissAlert = useCallback((id: string) => {
    setDismissed(prev => {
      const next = [...prev, id];
      // Bound localStorage growth — keep the most recent ids only.
      const capped = next.length > DISMISSED_CAP ? next.slice(next.length - DISMISSED_CAP) : next;
      try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(capped)); } catch { /* quota — ignore */ }
      return new Set(capped);
    });
  }, []);

  // Mark ALL currently-visible alerts as read in one shot. Unlike opening the
  // panel (which just bumps lastSeen), this dismisses every visible alert so
  // the panel clears immediately. Idempotent and resilient to quota errors.
  const markAllRead = useCallback(() => {
    setDismissed(prev => {
      const next = [...prev, ...alerts.map(a => a.id)];
      const capped = next.length > DISMISSED_CAP ? next.slice(next.length - DISMISSED_CAP) : next;
      try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(capped)); } catch { /* quota — ignore */ }
      return new Set(capped);
    });
    const now = Date.now();
    setLastSeen(now);
    try { localStorage.setItem(LAST_SEEN_KEY, String(now)); } catch { /* quota — ignore */ }
  }, [alerts]);

  const [lastScanMs, setLastScanMs] = useState<number | null>(null);

  // SSE connection — fetchAlerts defined above so it's safe to reference here.
  // Re-fetch on both system and alert events to keep the Alert Center in sync.
  const { connected: sseConnected } = useSSE(user?.token ?? null, {
    system: () => { setAlertOffset(0); void fetchAlerts(0, false); },
    alert:  () => { setAlertOffset(0); void fetchAlerts(0, false); },
    scanner_tick: (raw) => {
      const payload = raw as { ts?: number };
      if (payload.ts) setLastScanMs(payload.ts * 1000);
    },
  });

  useEffect(() => {
    void fetchAlerts(0, false);
  }, [fetchAlerts]);

  const visibleAlerts = useMemo(
    () => alerts.filter((a) => !dismissed.has(a.id)),
    [alerts, dismissed],
  );

  const unreadCount = useMemo(
    () => visibleAlerts.filter((a) => new Date(a.created_at).getTime() > lastSeen).length,
    [visibleAlerts, lastSeen],
  );

  const openAlertCenter = useCallback(() => {
    setIsAlertOpen(true);
    const now = Date.now();
    setLastSeen(now);
    localStorage.setItem(LAST_SEEN_KEY, String(now));
  }, []);

  const closeAlertCenter = useCallback(() => setIsAlertOpen(false), []);

  const alertCtx: AlertCenterCtx = useMemo(
    () => ({
      alerts: visibleAlerts,
      unreadCount,
      isOpen: isAlertOpen,
      openAlertCenter,
      closeAlertCenter,
      dismissAlert,
      markAllRead,
      loadMoreAlerts,
      hasMoreAlerts,
    }),
    [visibleAlerts, unreadCount, isAlertOpen, openAlertCenter, closeAlertCenter, dismissAlert, markAllRead, loadMoreAlerts, hasMoreAlerts],
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
          <Suspense fallback={<PageLoader />}>
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
          </Suspense>
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
