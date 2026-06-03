import { useEffect, useState } from "react";
import type { MarketFeedItem } from "../lib/api";

const LEAN_TONE: Record<string, string> = {
  UP: "text-grn",
  DOWN: "text-red",
  EVEN: "text-ink-2",
};
const LEAN_ARROW: Record<string, string> = { UP: "▲", DOWN: "▼", EVEN: "─" };

function fmtCountdown(s: number): string {
  if (s <= 0) return "closing";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

/**
 * Compact, auto-advancing single-line feed of live crypto up/down candle
 * markets. Cycles one asset at a time so it stays out of the way on Home.
 * Prices come from the synced markets table (CLOB) — no external spot feed.
 */
export function MarketFeed({ items, intervalMs = 3500 }: { items: MarketFeedItem[]; intervalMs?: number }) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (items.length <= 1) return;
    const id = setInterval(() => setIdx((i) => (i + 1) % items.length), intervalMs);
    return () => clearInterval(id);
  }, [items.length, intervalMs]);

  useEffect(() => {
    if (idx > items.length - 1) setIdx(0);
  }, [items.length, idx]);

  if (items.length === 0) return null;
  const it = items[Math.min(idx, items.length - 1)];
  const pct = Math.round(it.up_prob * 100);

  const leanColor = it.lean === "UP" ? "var(--grn,#00FF9C)" : it.lean === "DOWN" ? "var(--red,#FF2D55)" : "var(--gold,#F5C842)";

  return (
    <div className="bg-surface border border-border-1 clip-card px-3 pt-2 pb-1.5 mb-3 overflow-hidden">
      {/* header row */}
      <div className="flex items-center gap-2.5">
        <span className="font-hud text-[9px] font-bold tracking-[2px] text-ink-3 uppercase shrink-0">Feed</span>
        <span className="w-px h-3 bg-border-2 shrink-0" aria-hidden />
        <div
          key={idx}
          className="flex items-center gap-2 font-mono text-[11px] min-w-0 flex-1 overflow-hidden"
          style={{ animation: "fadeSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) both" }}
        >
          <span className="font-bold text-ink-1 shrink-0">{it.label}</span>
          <span className={`${LEAN_TONE[it.lean] ?? "text-ink-2"} font-bold shrink-0`}>
            {LEAN_ARROW[it.lean] ?? "─"} {pct}%
          </span>
          <span className="text-ink-4 truncate">· {fmtCountdown(it.seconds_to_close)}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {items.map((_, i) => (
            <span
              key={i}
              className="h-1 rounded-full transition-all"
              style={{
                width: i === idx ? "10px" : "4px",
                background: i === idx ? "var(--gold,#F5C842)" : "var(--ink-4,#2A3550)",
              }}
            />
          ))}
        </div>
      </div>
      {/* probability bar */}
      <div className="mt-1.5 h-[3px] bg-surface-3 overflow-hidden">
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${pct}%`, background: leanColor, boxShadow: `0 0 6px ${leanColor}` }}
        />
      </div>
    </div>
  );
}
