import type { AlertItem } from "../lib/api";

type Category = "TRADE" | "RISK" | "COPY" | "SYSTEM";

const CATEGORY_STYLE: Record<Category, { color: string; bg: string; border: string }> = {
  TRADE:  { color: "var(--gold)",  bg: "rgba(245,200,66,0.10)",  border: "rgba(245,200,66,0.30)" },
  RISK:   { color: "var(--red)",   bg: "rgba(255,45,85,0.10)",   border: "rgba(255,45,85,0.30)" },
  COPY:   { color: "var(--cyan)",  bg: "rgba(0,229,255,0.10)",   border: "rgba(0,229,255,0.30)" },
  SYSTEM: { color: "var(--ink-2)", bg: "rgba(143,163,196,0.08)", border: "rgba(143,163,196,0.20)" },
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
  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-[200]"
          style={{ background: "rgba(2,5,11,0.5)", backdropFilter: "blur(2px)" }}
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
          width: "min(360px, 92vw)",
          background: "var(--surface-2)",
          borderLeft: "1px solid var(--border-2)",
          transform: isOpen ? "translateX(0)" : "translateX(100%)",
          transition: "transform 0.25s cubic-bezier(0.22,1,0.36,1)",
          boxShadow: isOpen ? "-8px 0 32px rgba(0,0,0,0.6)" : "none",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-border-2">
          <span
            className="font-hud text-[13px] font-bold tracking-[3px] uppercase text-gold"
          >
            ALERT CENTER
          </span>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded text-ink-3 hover:text-ink-1 transition-colors bg-border-1"
            aria-label="Close Alert Center"
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
            <div className="flex flex-col items-center justify-center h-full gap-2 py-12">
              <span className="text-2xl" aria-hidden>🔔</span>
              <span className="font-mono text-[12px] text-ink-3">No alerts yet.</span>
            </div>
          ) : (
            <div className="divide-y divide-border-1">
              {alerts.map((alert) => {
                const cat = deriveCategory(alert);
                const style = CATEGORY_STYLE[cat];
                return (
                  <div
                    key={alert.id}
                    className="px-4 py-3"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {/* Category badge */}
                      <span
                        className="font-hud text-[8px] font-bold tracking-[1.5px] px-1.5 py-0.5 rounded-sm uppercase"
                        style={{ color: style.color, background: style.bg, border: `1px solid ${style.border}` }}
                      >
                        {cat}
                      </span>
                      {/* Relative timestamp */}
                      <span className="font-mono text-[9px] text-ink-3 ml-auto">
                        {relativeTime(alert.created_at)}
                      </span>
                    </div>
                    <div className="font-sans text-[12px] text-ink-1 font-semibold leading-snug">
                      {alert.title}
                    </div>
                    {alert.body && (
                      <div className="font-mono text-[10px] text-ink-3 mt-0.5 leading-snug">
                        {alert.body}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
