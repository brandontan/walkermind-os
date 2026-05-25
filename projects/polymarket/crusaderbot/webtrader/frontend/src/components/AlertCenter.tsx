import { useAlertCenter } from "../App";
import type { AlertItem } from "../lib/api";

type Category = "TRADE" | "RISK" | "COPY" | "SYSTEM";

const CATEGORY_STYLE: Record<Category, { color: string; bg: string; border: string }> = {
  TRADE:  { color: "var(--gold)",  bg: "var(--gold-10)",  border: "var(--gold-30)"  },
  RISK:   { color: "var(--red)",   bg: "var(--red-10)",   border: "var(--red-30)"   },
  COPY:   { color: "var(--cyan)",  bg: "var(--cyan-10)",  border: "var(--cyan-30)"  },
  SYSTEM: { color: "var(--ink-2)", bg: "var(--ink-2-08)", border: "var(--ink-2-20)" },
};

const CATEGORY_ICON: Record<Category, string> = {
  TRADE:  "⚡",
  RISK:   "⚠️",
  COPY:   "📡",
  SYSTEM: "🖥",
};

function deriveCategory(alert: AlertItem): Category {
  const s = (alert.severity ?? "").toLowerCase();
  const t = (alert.title ?? "").toLowerCase();
  if (s === "trade" || t.includes("trade") || t.includes("position") || t.includes("tp_") || t.includes("sl_"))
    return "TRADE";
  if (s === "copy" || t.includes("copy"))
    return "COPY";
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

export function AlertCenter({ isOpen, alerts, onClose }: Props) {
  const { dismissAlert, loadMoreAlerts, hasMoreAlerts, unreadCount } = useAlertCenter();

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
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-border-2 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="font-hud text-[13px] font-bold tracking-[3px] uppercase text-gold">
              Notifications
            </span>
            {unreadCount > 0 && (
              <span
                className="font-mono text-[9px] font-bold px-2 py-0.5 rounded-full"
                style={{ background: "rgba(245,200,66,0.15)", color: "var(--gold,#F5C842)", border: "1px solid rgba(245,200,66,0.3)" }}
              >
                {unreadCount} NEW
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded text-ink-3 hover:text-ink-1 transition-colors bg-border-1"
            aria-label="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Alert list */}
        <div className="flex-1 overflow-y-auto">
          {alerts.length === 0 ? (
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
                {alerts.map((alert) => {
                  const cat = deriveCategory(alert);
                  const style = CATEGORY_STYLE[cat];
                  const icon = CATEGORY_ICON[cat];
                  return (
                    <div key={alert.id} className="px-4 py-3 flex gap-3 group hover:bg-surface-3 transition-colors">
                      {/* Icon badge */}
                      <div
                        className="flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center text-[16px] mt-0.5"
                        style={{ background: style.bg, border: `1px solid ${style.border}` }}
                      >
                        {icon}
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start gap-1.5 mb-0.5">
                          <span className="font-sans text-[12px] text-ink-1 font-semibold leading-snug flex-1">
                            {alert.title}
                          </span>
                          {/* Dismiss */}
                          <button
                            type="button"
                            onClick={() => dismissAlert(alert.id)}
                            className="flex-shrink-0 w-5 h-5 flex items-center justify-center text-ink-4 hover:text-ink-2 opacity-0 group-hover:opacity-100 transition-all mt-0.5"
                            aria-label="Dismiss"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24"
                              fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                          </button>
                        </div>
                        {alert.body && (
                          <div className="font-mono text-[10px] text-ink-3 leading-snug mb-1 truncate">
                            {alert.body}
                          </div>
                        )}
                        <span className="font-mono text-[9px] text-ink-4">
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

        {/* Footer */}
        <div
          className="px-4 py-2.5 border-t border-border-2 flex items-center justify-between flex-shrink-0"
          style={{ background: "var(--surface)" }}
        >
          <span className="font-mono text-[9px] text-ink-4">
            {alerts.length} shown · tap × to dismiss
          </span>
        </div>
      </div>
    </>
  );
}
