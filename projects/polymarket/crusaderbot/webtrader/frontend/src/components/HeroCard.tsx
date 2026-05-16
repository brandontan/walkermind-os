import { useEffect, useRef, useState, type ReactNode } from "react";

export type RiskLevel = "safe" | "balanced" | "aggressive";

type Props = {
  /** Tiny label above the headline, e.g. "Equity" or "Auto Trade". */
  label: string;
  /** Numeric value triggers count-up; string (e.g. "BALANCED") renders as-is. */
  value: number | string;
  /** Cents suffix shown smaller, e.g. ".00". Only used when value is numeric. */
  cents?: string;
  /** Optional prefix character before numeric value, defaults to "$". Set "" to disable. */
  prefix?: string;
  /** Font-size for the headline. Default 58px for equity, override e.g. 42px on AutoTrade. */
  valueFontSize?: number;
  /** Meta row below the headline. */
  metaItems?: ReactNode;
  /** Status pill (ACTIVE, IDLE etc.) on left. */
  statusLabel?: string;
  /** Strategy code shown next to status, advanced only — caller can wrap in <AdvancedOnly>. */
  statusCode?: ReactNode;
  /** Risk tag pill on right of meta row. */
  risk?: RiskLevel | null;
  /** Primary CTA button. */
  ctaPrimary?: { label: string; onClick: () => void };
  /** Secondary ghost CTA. */
  ctaSecondary?: { label: string; onClick: () => void };
  /** Full-width danger CTA (replaces the two CTAs above). */
  ctaDanger?: { label: string; onClick: () => void };
};

const RISK_LABEL: Record<RiskLevel, string> = {
  safe:       "Safe",
  balanced:   "Balanced",
  aggressive: "Aggressive",
};

export function HeroCard({
  label,
  value,
  cents,
  prefix = "$",
  valueFontSize = 58,
  metaItems,
  statusLabel,
  statusCode,
  risk,
  ctaPrimary,
  ctaSecondary,
  ctaDanger,
}: Props) {
  const numeric = typeof value === "number";
  // Hook must run unconditionally; ignore the value when `value` is a string.
  const counted = useCountUp(numeric ? value : 0);
  const display = numeric ? counted : value;

  return (
    <div
      className="relative mb-3 overflow-hidden clip-card-lg p-[18px_16px_16px] border border-border-2"
      style={{
        background:
          "radial-gradient(circle at 80% 0%, rgba(245,200,66,0.10) 0%, transparent 50%), linear-gradient(170deg, #0E1830 0%, #0A1322 50%, #060B16 100%)",
      }}
    >
      {/* HUD corner crosses */}
      <Cross className="top-2 left-2" pos="tl" />
      <Cross className="top-2 right-2" pos="tr" />
      <Cross className="bottom-2 left-2" pos="bl" />
      <Cross className="bottom-2 right-2" pos="br" />

      {/* Sweep line */}
      <span
        className="absolute -top-px left-0 w-full h-0.5 animate-sweep pointer-events-none"
        style={{
          background:
            "linear-gradient(90deg, transparent, var(--gold,#F5C842), transparent)",
        }}
        aria-hidden
      />

      {/* Meta row */}
      {(statusLabel || risk) && (
        <div className="flex items-center justify-between mb-4 pl-1">
          {statusLabel && (
            <div className="flex items-center gap-2">
              <span
                className="w-[7px] h-[7px] rounded-full bg-grn animate-status-pulse"
                style={{ boxShadow: "0 0 10px var(--grn,#00FF9C)" }}
                aria-hidden
              />
              <span className="font-mono text-[9px] font-bold tracking-[2.5px] text-gold uppercase">
                {statusLabel}
              </span>
              {statusCode && (
                <span className="font-mono text-[8px] text-ink-3 tracking-[1.5px]">
                  · {statusCode}
                </span>
              )}
            </div>
          )}
          {risk && <RiskTag risk={risk} />}
        </div>
      )}

      {/* Label */}
      <div className="font-mono text-[9px] font-bold tracking-[3px] text-ink-3 uppercase mb-1 pl-1">
        <span className="text-gold">◢ </span>{label}
      </div>

      {/* Headline */}
      <div
        className="font-display leading-[0.95] pl-1"
        style={{
          fontSize: `${valueFontSize}px`,
          letterSpacing: "-1px",
          background:
            "linear-gradient(180deg, #FFFFFF 0%, #FFE066 60%, #C99A1F 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          textShadow: "0 0 30px rgba(245,200,66,0.2)",
        }}
      >
        {numeric ? `${prefix}${display}` : display}
        {numeric && cents && (
          <span
            className="opacity-70"
            style={{ fontSize: `${Math.round(valueFontSize * 0.48)}px`, letterSpacing: 0 }}
          >
            {cents}
          </span>
        )}
      </div>

      {/* Meta items */}
      {metaItems && (
        <div className="flex items-center gap-2.5 mt-2 pl-1 font-mono text-[11px] text-ink-2 tracking-[0.5px] flex-wrap">
          {metaItems}
        </div>
      )}

      {/* CTAs */}
      {(ctaPrimary || ctaSecondary || ctaDanger) && (
        <div className={ctaDanger ? "mt-4" : "grid grid-cols-[1.4fr_1fr] gap-2 mt-4"}>
          {ctaPrimary && !ctaDanger && (
            <button
              onClick={ctaPrimary.onClick}
              className="clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-3 px-2.5 transition-all flex items-center justify-center gap-1.5 cursor-pointer"
              style={{
                background: "linear-gradient(135deg, #F5C842 0%, #C99A1F 100%)",
                color: "#1A1100",
                boxShadow:
                  "0 0 0 1px rgba(245,200,66,0.4), 0 4px 16px rgba(245,200,66,0.2)",
              }}
            >
              {ctaPrimary.label}
              <span className="font-mono opacity-60">▸</span>
            </button>
          )}
          {ctaSecondary && !ctaDanger && (
            <button
              onClick={ctaSecondary.onClick}
              className="clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-3 px-2.5 transition-colors flex items-center justify-center gap-1.5 cursor-pointer bg-surface-2 text-ink-1 border border-border-2 hover:border-gold hover:text-gold hover:bg-surface-3"
            >
              {ctaSecondary.label}
            </button>
          )}
          {ctaDanger && (
            <button
              onClick={ctaDanger.onClick}
              className="clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-3 px-2.5 transition-colors flex items-center justify-center gap-1.5 cursor-pointer w-full text-red border"
              style={{
                background: "rgba(255,45,85,0.08)",
                borderColor: "rgba(255,45,85,0.3)",
              }}
            >
              {ctaDanger.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Cross({ pos, className }: { pos: "tl" | "tr" | "bl" | "br"; className?: string }) {
  const borders: Record<typeof pos, string> = {
    tl: "1px 0 0 1px",
    tr: "1px 1px 0 0",
    bl: "0 0 1px 1px",
    br: "0 1px 1px 0",
  } as const;
  return (
    <span
      className={`absolute w-3.5 h-3.5 border-solid border-gold opacity-70 z-[2] ${className ?? ""}`}
      style={{ borderWidth: borders[pos] }}
      aria-hidden
    />
  );
}

function RiskTag({ risk }: { risk: RiskLevel }) {
  return (
    <span
      className="inline-flex items-baseline gap-1.5 font-mono text-[9px] font-bold tracking-[2px] py-1 px-2.5 uppercase clip-tab"
      style={{
        background: "rgba(245,200,66,0.10)",
        color: "var(--gold,#F5C842)",
        border: "1px solid rgba(245,200,66,0.3)",
      }}
    >
      <span className="text-ink-3 mr-0.5">[</span>
      {RISK_LABEL[risk]}
      <span className="text-ink-3 ml-0.5">]</span>
    </span>
  );
}

/** Ease-out cubic count-up over 1200ms. Re-runs when target changes. */
function useCountUp(target: number, duration = 1200): string {
  const [display, setDisplay] = useState<string>(() => formatThousands(target));
  const lastTarget = useRef<number>(target);

  useEffect(() => {
    // Skip the count-up animation if value didn't actually change.
    if (lastTarget.current === target) return;
    lastTarget.current = target;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      const val = Math.floor(target * eased);
      setDisplay(formatThousands(val));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);

  return display;
}

function formatThousands(n: number): string {
  return Math.floor(n).toLocaleString("en-US");
}
