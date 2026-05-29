import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AlertCenter } from "./components/AlertCenter";
import { BottomNav } from "./components/BottomNav";
import { DesktopSidebar } from "./components/DesktopSidebar";
import { ErrorBoundary } from "./components/ErrorBoundary";
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
const AdminPage      = lazy(() => import("./pages/AdminPage").then(m => ({ default: m.AdminPage })));

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[40vh]">
      <span className="w-5 h-5 rounded-full border-2 border-ink-4 border-t-grn animate-spin" />
    </div>
  );
}

const LAST_SEEN_KEY = "alertCenter_lastSeen";
const DISMISSED_KEY = "alertCenter_dismissed";
const SEEN_IDS_KEY = "alertCenter_seenIds";
const MARK_ALL_READ_AT_KEY = "alertCenter_markAllReadAt";
const DISMISSED_CAP = 500;
const SEEN_IDS_CAP = 500;

function loadDismissed(): Set<string> {
  try {
    const stored = localStorage.getItem(DISMISSED_KEY);
    return stored ? new Set<string>(JSON.parse(stored) as string[]) : new Set<string>();
  } catch {
    return new Set<string>();
  }
}

function loadSeenIds(): Set<string> {
  try {
    const stored = localStorage.getItem(SEEN_IDS_KEY);
    return stored ? new Set<string>(JSON.parse(stored) as string[]) : new Set<string>();
  } catch {
    return new Set<string>();
  }
}

function loadMarkAllReadAt(): number {
  try {
    const stored = localStorage.getItem(MARK_ALL_READ_AT_KEY);
    const parsed = stored ? Number(stored) : 0;
    return Number.isFinite(parsed) ? parsed : 0;
  } catch {
    return 0;
  }
}

interface AlertCenterCtx {
  alerts: AlertItem[];
  unreadCount: number;
  // Persistent per-alert-ID seen set. An alert is "unread" iff its ID is NOT
  // in this set. Survives panel re-opens so the gold-bar treatment sticks
  // until the user explicitly acknowledges (dismiss or Mark all read). Bumped
  // ONLY by user action — opening the panel does NOT auto-mark anything.
  seenIds: Set<string>;
  isOpen: boolean;
  openAlertCenter: () => void;
  closeAlertCenter: () => void;
  dismissAlert: (id: string) => void;
  markSeen: (id: string) => void;
  markAllRead: () => void;
  loadMoreAlerts: () => Promise<void>;
  hasMoreAlerts: boolean;
}

export const AlertCenterContext = createContext<AlertCenterCtx>({
  alerts: [],
  unreadCount: 0,
  seenIds: new Set<string>(),
  isOpen: false,
  openAlertCenter: () => undefined,
  closeAlertCenter: () => undefined,
  dismissAlert: () => undefined,
  markSeen: () => undefined,
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

// App-wide trading mode ("paper" | "live"), fetched once from /me and refreshed
// on live enable/disable. Lets any TopBar render the correct LIVE/PAPER pill
// even on pages that don't fetch the mode themselves.
export const TradingModeContext = createContext<string>("paper");

export function useTradingMode(): string {
  return useContext(TradingModeContext);
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
  // Persistent seen-ID set. Unread alerts are those whose ID is NOT in this
  // set — the gold-bar treatment persists across panel re-opens until the
  // user explicitly dismisses or hits "Mark all read". (Legacy lastSeen
  // timestamp is still written to localStorage for backward compatibility
  // with any older client cache.)
  const [seenIds, setSeenIds] = useState<Set<string>>(loadSeenIds);
  // Hard "everything before this is read" watermark. Updated by markAllRead.
  // Survives page refresh — visibleAlerts filters out anything with
  // created_at <= markAllReadAt so the user does NOT see the same closed
  // positions pop back up after the next /positions fetch. This is the
  // user-visible fix for "I marked all read but refresh brings them all
  // back" — the old design only tracked the in-memory alert IDs at the time
  // of the click, which were dropped once the backend served new rows.
  const [markAllReadAt, setMarkAllReadAt] = useState<number>(loadMarkAllReadAt);
  const setLastSeen = (v: number) => { try { localStorage.setItem(LAST_SEEN_KEY, String(v)); } catch { /* quota */ } };

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
      // Newest always on top: system + trade alerts are separate sources, so a
      // plain concat leaves trade alerts after older system ones. Sort the full
      // merged list by created_at descending.
      const byNewest = (a: AlertItem, b: AlertItem) =>
        (b.created_at ? Date.parse(b.created_at) : 0) - (a.created_at ? Date.parse(a.created_at) : 0);
      setAlerts(prev => (append ? [...prev, ...newItems] : newItems).slice().sort(byNewest));
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

  // Mark ALL currently-visible alerts as read in one shot. Sets the persistent
  // markAllReadAt watermark so that on the next /positions or /alerts fetch
  // (or full page refresh) we do NOT re-surface anything that pre-dates the
  // click. Still adds IDs to dismissed + seenIds for back-compat with the
  // legacy ID-based path, but the watermark is what actually keeps stale
  // alerts gone across reloads.
  const markAllRead = useCallback(() => {
    setDismissed(prev => {
      const next = [...prev, ...alerts.map(a => a.id)];
      const capped = next.length > DISMISSED_CAP ? next.slice(next.length - DISMISSED_CAP) : next;
      try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(capped)); } catch { /* quota — ignore */ }
      return new Set(capped);
    });
    setSeenIds(prev => {
      const next = [...prev, ...alerts.map(a => a.id)];
      const capped = next.length > SEEN_IDS_CAP ? next.slice(next.length - SEEN_IDS_CAP) : next;
      try { localStorage.setItem(SEEN_IDS_KEY, JSON.stringify(capped)); } catch { /* quota — ignore */ }
      return new Set(capped);
    });
    const now = Date.now();
    setMarkAllReadAt(now);
    try { localStorage.setItem(MARK_ALL_READ_AT_KEY, String(now)); } catch { /* quota — ignore */ }
    setLastSeen(now);
    try { localStorage.setItem(LAST_SEEN_KEY, String(now)); } catch { /* quota — ignore */ }
  }, [alerts]);

  // Per-alert "mark as read" without dismissing. Used when an unread alert
  // is auto-acknowledged after the user has had time to read it (panel open
  // for >2s with the card visible). Keeps the alert in the list but drops the
  // gold-bar treatment.
  const markSeen = useCallback((id: string) => {
    setSeenIds(prev => {
      if (prev.has(id)) return prev;
      const next = [...prev, id];
      const capped = next.length > SEEN_IDS_CAP ? next.slice(next.length - SEEN_IDS_CAP) : next;
      try { localStorage.setItem(SEEN_IDS_KEY, JSON.stringify(capped)); } catch { /* quota — ignore */ }
      return new Set(capped);
    });
  }, []);

  const [lastScanMs, setLastScanMs] = useState<number | null>(null);

  // App-wide trading mode. Fetched from /me when authed and refreshed on
  // system SSE events (live enable/disable broadcasts one), so the TopBar pill
  // reflects reality on every page — not a hardcoded "paper".
  const [tradingMode, setTradingMode] = useState<string>("paper");
  const refreshTradingMode = useCallback(() => {
    if (!user) return;
    api.getMe()
      .then((me) => setTradingMode(me.trading_mode || "paper"))
      .catch(() => { /* leave last-known mode; non-fatal for chrome */ });
  }, [api, user]);

  useEffect(() => { refreshTradingMode(); }, [refreshTradingMode]);

  // SSE connection — fetchAlerts defined above so it's safe to reference here.
  // Re-fetch on both system and alert events to keep the Alert Center in sync.
  const { connected: sseConnected } = useSSE(user?.token ?? null, {
    system: () => { setAlertOffset(0); void fetchAlerts(0, false); refreshTradingMode(); },
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
    () => alerts.filter((a) => {
      if (dismissed.has(a.id)) return false;
      // Persistent "mark all read" watermark — anything timestamped before
      // the click is hidden permanently. Alerts without a parseable
      // created_at fall through (e.g. system alerts with timing missing) so
      // a malformed row never silently disappears.
      //
      // Date.parse treats a timezone-naive ISO string as LOCAL time but
      // markAllReadAt comes from Date.now() (UTC), so a missing 'Z' would
      // skew the comparison by the user's UTC offset. Backend rows should
      // already be tz-aware (TIMESTAMPTZ → asyncpg → .isoformat() with
      // +00:00), but normalise defensively so a future writer dropping the
      // suffix never silently wipes alerts in negative-UTC timezones.
      if (markAllReadAt > 0 && a.created_at) {
        const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(a.created_at);
        const normalized = hasTz ? a.created_at : `${a.created_at}Z`;
        const ts = Date.parse(normalized);
        if (Number.isFinite(ts) && ts <= markAllReadAt) return false;
      }
      return true;
    }),
    [alerts, dismissed, markAllReadAt],
  );

  // Unread = alert whose ID hasn't been added to seenIds yet. Persistent
  // across panel re-opens; only flips when the user acknowledges (dismiss,
  // Mark all read, or per-alert markSeen).
  const unreadCount = useMemo(
    () => visibleAlerts.filter((a) => !seenIds.has(a.id)).length,
    [visibleAlerts, seenIds],
  );

  const openAlertCenter = useCallback(() => {
    setIsAlertOpen(true);
    // Bump lastSeen so the unread-count badge clears immediately for the
    // legacy timestamp-based consumers, but do NOT touch seenIds — the
    // per-card gold-bar treatment persists until explicit user action.
    const now = Date.now();
    setLastSeen(now);
    localStorage.setItem(LAST_SEEN_KEY, String(now));
  }, []);

  const closeAlertCenter = useCallback(() => setIsAlertOpen(false), []);

  const alertCtx: AlertCenterCtx = useMemo(
    () => ({
      alerts: visibleAlerts,
      unreadCount,
      seenIds,
      isOpen: isAlertOpen,
      openAlertCenter,
      closeAlertCenter,
      markSeen,
      dismissAlert,
      markAllRead,
      loadMoreAlerts,
      hasMoreAlerts,
    }),
    [visibleAlerts, unreadCount, seenIds, isAlertOpen, openAlertCenter, closeAlertCenter, markSeen, dismissAlert, markAllRead, loadMoreAlerts, hasMoreAlerts],
  );

  return (
    <TradingModeContext.Provider value={tradingMode}>
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
          <ErrorBoundary>
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
              <Route
                path="/admin"
                element={user ? <AdminPage /> : <Navigate to="/auth" replace />}
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
          </ErrorBoundary>
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
    </TradingModeContext.Provider>
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
