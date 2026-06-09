import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { useAlertCenter } from "../App";
import type { AlertItem, AlertMetadata } from "../lib/api";

type Category = "TRADE" | "SIGNAL" | "RISK" | "SYSTEM";

const CATEGORY_STYLE: Record<Category, { color: string; bg: string; border: string }> = {
  TRADE:  { color: "var(--gold)",  bg: "var(--gold-10)",  border: "var(--gold-30)"  },
  SIGNAL: { color: "var(--cyan)",  bg: "var(--cyan-10)",  border: "var(--cyan-30)"  },
  RISK:   { color: "var(--red)",   bg: "var(--red-10)",   border: "var(--red-30)"   },
  SYSTEM: { color: "var(--ink-2)", bg: "var(--ink-2-08)", border: "var(--ink-2-20)" },
};

// Icon by alert_kind first (precise), category fallback (legacy rows). The
// trade-lifecycle icons mirror Kreo / Polymarket conventions: ⚡ entry,
// 🎯 TP, 🛑 SL, 🏁 resolution, ✅ manual close, 🚨 emergency, 🐋 copy.
const KIND_ICON: Record<string, string> = {
  trade_opened: "⚡",
  copy_trade_opened: "🐋",
  tp_hit: "🎯",
  sl_hit: "🛑",
  resolution_win: "🏁",
  resolution_loss: "🏁",
  force_close: "🚨",
  strategy_exit: "📉",
  manual_close: "✅",
  emergency_close: "🚨",
  market_expired: "⏰",
  close_failed: "⚠️",
  risk: "⚠️",
  system: "🖥",
};

const CATEGORY_ICON: Record<Category, string> = {
  TRADE:  "⚡",
  SIGNAL: "📡",
  RISK:   "⚠️",
  SYSTEM: "🖥",
};

// Map alert_kind → visual category for the icon-badge background.
const KIND_CATEGORY: Record<string, Category> = {
  trade_opened: "TRADE",
  copy_trade_opened: "TRADE",
  tp_hit: "TRADE",
  sl_hit: "RISK",
  resolution_win: "TRADE",
  resolution_loss: "RISK",
  force_close: "RISK",
  strategy_exit: "TRADE",
  manual_close: "TRADE",
  emergency_close: "RISK",
  market_expired: "SYSTEM",
  close_failed: "RISK",
  risk: "RISK",
  system: "SYSTEM",
};

function deriveCategory(alert: AlertItem): Category {
  // Prefer alert_kind (precise, set by backend on new writes).
  if (alert.alert_kind && KIND_CATEGORY[alert.alert_kind]) {
    return KIND_CATEGORY[alert.alert_kind];
  }
  // Legacy heuristic fallback (pre-072 rows have no alert_kind).
  const s = (alert.severity ?? "").toLowerCase();
  const t = (alert.title ?? "").toLowerCase();
  if (s === "copy" || s === "signal" || t.includes("signal") || t.includes("copy"))
    return "SIGNAL";
  if (s === "trade" || t.includes("trade") || t.includes("position") || t.includes("tp_") || t.includes("sl_"))
    return "TRADE";
  if (s === "error" || s === "risk" || t.includes("risk") || t.includes("kill") || t.includes("drawdown"))
    return "RISK";
  return "SYSTEM";
}

function relativeTime(ts: string | Date): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return "—";
  }
}

type Props = {
  isOpen: boolean;
  alerts: AlertItem[];
  onClose: () => void;
};

// Belt-and-suspenders HTML strip on render. The backend now strips when
// persisting (notification_prefs._strip_html_for_web), but operator-pushed
// broadcast rows or any pre-fix data in the DB might still contain tags.
function stripHtml(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function formatMoney(n: number | undefined): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  return `$${n.toFixed(2)}`;
}

function formatSignedMoney(n: number | undefined): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  // Round first so very small non-zero floats (e.g. 0.003) collapse to "Even"
  // instead of rendering as "+$0.00". `n === 0` alone misses these cases.
  const rounded = Math.abs(n).toFixed(2);
  if (rounded === "0.00") return "Even";
  const sign = n > 0 ? "+" : "−";
  return `${sign}$${rounded}`;
}

function formatPrice(n: number | undefined): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  return n.toFixed(3);
}

function formatPct(n: number | undefined): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

// P&L color by sign — green/red/muted. Returns a CSS var for theme parity.
function pnlColor(pnl: number | undefined): string {
  if (pnl === undefined || pnl === null || !Number.isFinite(pnl) || pnl === 0) return "var(--ink-2)";
  return pnl > 0 ? "var(--grn, #4ade80)" : "var(--red, #f87171)";
}

function sideColor(side: string | undefined): string {
  if (!side) return "var(--ink-3)";
  const s = side.toUpperCase();
  if (s === "YES") return "var(--grn, #4ade80)";
  if (s === "NO") return "var(--red, #f87171)";
  return "var(--ink-2)";
}

// Truncate the market title to a reasonable card width (full string preserved
// in the `title` attribute so hover reveals the rest).
function shortMarket(label: string | undefined, max = 38): string {
  if (!label) return "—";
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

// ─────────────────────────────────────────────────────────────────────────────
// Typed card renderers — one per alert_kind cluster. Each returns the inner
// body content; the outer card chrome (icon badge, header row, dismiss, time)
// stays in the parent so layout is consistent across kinds.
// ─────────────────────────────────────────────────────────────────────────────

function EntryBody({ md }: { md: AlertMetadata }) {
  const fullLabel = md.market_label ?? "—";
  return (
    <div className="space-y-1">
      <div className="font-mono text-[10.5px] text-ink-2 leading-snug break-words" title={fullLabel}>
        {shortMarket(fullLabel)}
      </div>
      <div className="flex items-center gap-2 flex-wrap font-mono text-[10px]">
        <span
          className="px-1.5 py-[1px] rounded font-bold text-[9.5px]"
          style={{ background: "rgba(255,255,255,0.04)", color: sideColor(md.side), border: `1px solid ${sideColor(md.side)}30` }}
        >
          {md.side ?? "—"}
        </span>
        <span className="text-ink-3">{formatMoney(md.size_usdc)}</span>
        <span className="text-ink-4">@</span>
        <span className="text-ink-2 font-bold">{formatPrice(md.entry_price)}</span>
      </div>
      <div className="flex items-center gap-3 font-mono text-[9.5px] text-ink-4">
        <span>TP {formatPct(md.tp_pct)}</span>
        <span>SL {formatPct(md.sl_pct)}</span>
        {md.strategy && (
          <span className="ml-auto text-ink-3 font-bold tracking-[0.5px]">{md.strategy}</span>
        )}
      </div>
    </div>
  );
}

function ExitBody({ md, kind }: { md: AlertMetadata; kind: string }) {
  const fullLabel = md.market_label ?? "—";
  const verb =
    kind === "tp_hit" ? "TP" :
    kind === "sl_hit" ? "SL" :
    kind === "resolution_win" ? "Settled" :
    kind === "resolution_loss" ? "Settled" :
    kind === "force_close" ? "Force-closed" :
    kind === "manual_close" ? "Closed" :
    kind === "emergency_close" ? "Emergency-closed" :
    "Closed";
  return (
    <div className="space-y-1">
      <div className="font-mono text-[10.5px] text-ink-2 leading-snug break-words" title={fullLabel}>
        {shortMarket(fullLabel)}
      </div>
      <div className="flex items-center gap-2 flex-wrap font-mono text-[10px]">
        <span
          className="px-1.5 py-[1px] rounded font-bold text-[9.5px]"
          style={{ background: "rgba(255,255,255,0.04)", color: sideColor(md.side), border: `1px solid ${sideColor(md.side)}30` }}
        >
          {md.side ?? "—"}
        </span>
        <span className="text-ink-3">{verb}</span>
        <span className="text-ink-4">@</span>
        <span className="text-ink-2 font-bold">{formatPrice(md.exit_price)}</span>
        <span
          className="ml-auto font-bold"
          style={{ color: pnlColor(md.pnl_usdc) }}
        >
          {formatSignedMoney(md.pnl_usdc)}
        </span>
      </div>
    </div>
  );
}

function ExpiredBody({ md }: { md: AlertMetadata }) {
  const fullLabel = md.market_label ?? "—";
  return (
    <div className="space-y-1">
      <div className="font-mono text-[10.5px] text-ink-2 leading-snug break-words" title={fullLabel}>
        {shortMarket(fullLabel)}
      </div>
      <div className="font-mono text-[10px] text-ink-3">
        Market expired — capital returned {formatMoney(md.size_usdc)}
      </div>
    </div>
  );
}

function FailedBody({ md }: { md: AlertMetadata }) {
  const fullLabel = md.market_label ?? "—";
  return (
    <div className="space-y-1">
      <div className="font-mono text-[10.5px] text-ink-2 leading-snug break-words" title={fullLabel}>
        {shortMarket(fullLabel)}
      </div>
      {md.error && (
        <div className="font-mono text-[9.5px] text-ink-3 leading-snug break-words">
          {md.error}
        </div>
      )}
    </div>
  );
}

// Plain-text fallback for legacy rows / system messages with no metadata.
function FallbackBody({ body }: { body: string | null | undefined }) {
  const text = stripHtml(body);
  if (!text) return null;
  return (
    <div className="font-mono text-[10px] text-ink-3 leading-snug whitespace-pre-line break-words">
      {text}
    </div>
  );
}

// Title override per kind — the backend writes generic web titles ("Take-profit
// hit", "Trade opened"), but we can do better on the visual surface.
function kindTitle(alert: AlertItem): string {
  const k = (alert.alert_kind ?? "").toString();
  const titleMap: Record<string, string> = {
    trade_opened: "Trade opened",
    copy_trade_opened: "Copy trade opened",
    tp_hit: "Take-profit hit",
    sl_hit: "Stop-loss hit",
    resolution_win: "Resolved — Won",
    resolution_loss: "Resolved — Lost",
    force_close: "Force close",
    strategy_exit: "Strategy exit",
    manual_close: "Manual close",
    emergency_close: "Emergency close",
    market_expired: "Market expired",
    close_failed: "Close failed",
  };
  // `||` (not `??`) so empty strings from stripHtml fall through to the
  // "Notification" fallback instead of rendering an empty title row.
  return titleMap[k] || stripHtml(alert.title) || "Notification";
}

// ─────────────────────────────────────────────────────────────────────────────
// Dedup: when a strategy_exit fires for the same (user, market) within 60s
// of a more-specific exit (tp_hit / sl_hit / resolution_*), the strategy_exit
// row is redundant noise. Drop it client-side; the backend write is preserved
// for audit purposes.
// ─────────────────────────────────────────────────────────────────────────────
function dedupAlerts(alerts: AlertItem[]): AlertItem[] {
  const out: AlertItem[] = [];
  for (const a of alerts) {
    if (a.alert_kind !== "strategy_exit") { out.push(a); continue; }
    const market = a.metadata?.market_id;
    if (!market) { out.push(a); continue; }
    const aTs = new Date(a.created_at).getTime();
    // Look for a sibling exit on the same market within 60s in either direction.
    const sibling = alerts.find((b) =>
      b.id !== a.id &&
      b.metadata?.market_id === market &&
      (b.alert_kind === "tp_hit" || b.alert_kind === "sl_hit" ||
       b.alert_kind === "resolution_win" || b.alert_kind === "resolution_loss" ||
       b.alert_kind === "force_close" || b.alert_kind === "manual_close" ||
       b.alert_kind === "emergency_close") &&
      Math.abs(new Date(b.created_at).getTime() - aTs) < 60_000
    );
    if (!sibling) out.push(a);
  }
  return out;
}

export function AlertCenter({ isOpen, alerts, onClose }: Props) {
  const { dismissAlert, markAllRead, loadMoreAlerts, hasMoreAlerts, unreadCount, seenIds } = useAlertCenter();
  const navigate = useNavigate();

  // Apply dedup once per render of the panel.
  const visibleAlerts = useMemo(() => dedupAlerts(alerts), [alerts]);

  // "Preferences" link target — opens the Settings page where alert filtering
  // already lives. Keeps the panel a viewer + actions surface; settings are
  // configured elsewhere.
  const openPreferences = () => {
    onClose();
    navigate("/settings");
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-[200]"
          style={{ background: "var(--overlay-bg)", backdropFilter: "blur(2px)" }}
          onClick={onClose}
          aria-hidden
        />
      )}

      {/* Slide-in panel */}
      <div
        role="dialog"
        aria-label="Alert Center"
        className="fixed top-0 right-0 h-full z-[201] flex flex-col"
        style={{
          width: "min(380px, 96vw)",
          background: "var(--surface-2)",
          borderLeft: "1px solid var(--border-2)",
          transform: isOpen ? "translateX(0)" : "translateX(100%)",
          transition: "transform 0.25s cubic-bezier(0.22,1,0.36,1)",
          boxShadow: isOpen ? `-8px 0 32px var(--shadow-deep)` : "none",
        }}
      >
        {/* Header — title + NEW badge on top row, Mark all read + close on actions row.
            Two-row layout avoids the badge/link collision visible in the prior screenshot
            when "10 NEW" + "Mark all read" + × competed for horizontal space at mobile widths. */}
        <div className="flex flex-col gap-2 px-4 pt-3.5 pb-3 border-b border-border-2 flex-shrink-0">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-hud text-[13px] font-bold tracking-[3px] uppercase text-gold">
                Notifications
              </span>
              {unreadCount > 0 && (
                <span
                  className="font-mono text-[9px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap"
                  style={{ background: "rgba(245,200,66,0.15)", color: "var(--gold,#F5C842)", border: "1px solid rgba(245,200,66,0.3)" }}
                >
                  {unreadCount} NEW
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="w-7 h-7 flex-shrink-0 flex items-center justify-center rounded text-ink-3 hover:text-ink-1 transition-colors bg-border-1"
              aria-label="Close"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          {visibleAlerts.length > 0 && (
            <div className="flex items-center justify-end">
              <button
                type="button"
                onClick={markAllRead}
                className="font-mono text-[10px] text-ink-3 hover:text-gold transition-colors whitespace-nowrap"
                aria-label="Mark all read"
              >
                Mark all read
              </button>
            </div>
          )}
        </div>

        {/* Alert list */}
        <div className="flex-1 overflow-y-auto">
          {visibleAlerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 py-12">
              <span className="text-3xl opacity-40" aria-hidden>🔔</span>
              <span className="font-mono text-[11px] text-ink-4">No notifications yet.</span>
              <span className="font-mono text-[10px] text-ink-4 text-center px-8 leading-relaxed">
                Trade closures and system events will appear here.
              </span>
            </div>
          ) : (
            <div>
              <div className="divide-y divide-border-1">
                {visibleAlerts.map((alert) => {
                  const cat = deriveCategory(alert);
                  const style = CATEGORY_STYLE[cat];
                  const kind = (alert.alert_kind ?? "").toString();
                  const icon = KIND_ICON[kind] ?? CATEGORY_ICON[cat];
                  const md = (alert.metadata ?? {}) as AlertMetadata;
                  const isUnread = !seenIds.has(alert.id);
                  const hasTypedRenderer =
                    kind === "trade_opened" || kind === "copy_trade_opened" ||
                    kind === "tp_hit" || kind === "sl_hit" ||
                    kind === "resolution_win" || kind === "resolution_loss" ||
                    kind === "force_close" || kind === "strategy_exit" ||
                    kind === "manual_close" || kind === "emergency_close" ||
                    kind === "market_expired" || kind === "close_failed";
                  const titleStr = hasTypedRenderer ? kindTitle(alert) : stripHtml(alert.title);
                  return (
                    <div
                      key={alert.id}
                      className="relative px-4 py-3 flex gap-3 hover:bg-surface-3 transition-colors"
                      style={isUnread ? { background: "rgba(245,200,66,0.04)" } : undefined}
                    >
                      {/* Unread accent bar — runs the full left edge of the card */}
                      {isUnread && (
                        <span
                          className="absolute left-0 top-0 bottom-0 w-[3px]"
                          style={{ background: "var(--gold, #F5C842)" }}
                          aria-hidden
                        />
                      )}
                      {/* Icon badge */}
                      <div
                        className="flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center text-[16px] mt-0.5"
                        style={{ background: style.bg, border: `1px solid ${style.border}` }}
                      >
                        {icon}
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start gap-1.5 mb-1">
                          {isUnread && (
                            <span
                              className="inline-block w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0"
                              style={{ background: "var(--gold, #F5C842)", boxShadow: "0 0 6px rgba(245,200,66,0.6)" }}
                              aria-label="Unread"
                            />
                          )}
                          <span
                            className={`font-sans text-[12px] leading-snug flex-1 ${
                              isUnread ? "text-ink-1 font-bold" : "text-ink-2 font-semibold"
                            }`}
                          >
                            {titleStr}
                            {md.mode && md.mode.toLowerCase() !== "paper" && (
                              <span className="ml-1.5 text-[9px] font-mono font-bold uppercase tracking-wider text-amber-400">
                                {md.mode}
                              </span>
                            )}
                          </span>
                          <button
                            type="button"
                            onClick={() => dismissAlert(alert.id)}
                            className="flex-shrink-0 w-5 h-5 flex items-center justify-center text-ink-4 hover:text-ink-1 transition-colors mt-0.5"
                            aria-label="Dismiss"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24"
                              fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                          </button>
                        </div>

                        {/* Typed card body by alert_kind, or fallback to body text. */}
                        {kind === "trade_opened" || kind === "copy_trade_opened" ? (
                          <EntryBody md={md} />
                        ) : kind === "tp_hit" || kind === "sl_hit" ||
                            kind === "resolution_win" || kind === "resolution_loss" ||
                            kind === "force_close" || kind === "strategy_exit" ||
                            kind === "manual_close" || kind === "emergency_close" ? (
                          <ExitBody md={md} kind={kind} />
                        ) : kind === "market_expired" ? (
                          <ExpiredBody md={md} />
                        ) : kind === "close_failed" ? (
                          <FailedBody md={md} />
                        ) : (
                          <FallbackBody body={alert.body} />
                        )}

                        <span className="font-mono text-[9px] text-ink-4 block mt-1.5">
                          {relativeTime(alert.created_at)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Load more */}
              {hasMoreAlerts && (
                <button
                  type="button"
                  onClick={() => void loadMoreAlerts()}
                  className="w-full py-3 font-mono text-[10px] text-ink-3 hover:text-gold transition-colors border-t border-border-1"
                >
                  Load more
                </button>
              )}
            </div>
          )}
        </div>

        {/* Footer — shown count on the left, Preferences gear on the right. */}
        <div
          className="px-4 py-2.5 border-t border-border-2 flex items-center justify-between flex-shrink-0"
          style={{ background: "var(--surface)" }}
        >
          <span className="font-mono text-[9px] text-ink-4">
            {visibleAlerts.length > 0
              ? `${visibleAlerts.length} shown · tap × to dismiss`
              : "No new notifications"}
          </span>
          <button
            type="button"
            onClick={openPreferences}
            className="font-mono text-[9px] font-bold tracking-[2px] uppercase text-ink-3 hover:text-gold transition-colors flex items-center gap-1"
            aria-label="Preferences"
          >
            <span aria-hidden>⚙</span>
            Preferences
          </button>
        </div>
      </div>
    </>
  );
}

// Export dedupAlerts so a future test suite can pin the 60s window logic
// without re-instantiating the panel. AlertKind is intentionally NOT
// re-exported — consumers import it directly from lib/api.ts.
export { dedupAlerts };
