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

  return (
    <div className="flex items-center gap-2.5 bg-surface border border-border-1 clip-card px-3 py-1.5 mb-3 overflow-hidden">
      <span className="font-hud text-[9px] font-bold tracking-[2px] text-ink-3 uppercase shrink-0">
        Market Feed
      </span>
      <span className="w-px h-3 bg-border-2 shrink-0" aria-hidden />
      <div
        key={idx}
        className="flex items-center gap-2 font-mono text-[11px] min-w-0 truncate"
        style={{ animation: "fadeSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) both" }}
      >
        <span className="font-bold text-ink-1">{it.label}</span>
        <span className={`${LEAN_TONE[it.lean] ?? "text-ink-2"} font-semibold`}>
          {LEAN_ARROW[it.lean] ?? "─"} {pct}% UP
        </span>
        <span className="text-ink-3">· {fmtCountdown(it.seconds_to_close)} to close</span>
      </div>
      <div className="flex items-center gap-1 ml-auto shrink-0">
        {items.map((_, i) => (
          <span
            key={i}
            className="h-1 rounded-full transition-all"
            style={{
              width: i === idx ? "10px" : "4px",
              background: i === idx ? "var(--gold, #F5C842)" : "var(--ink-4, #2A3550)",
            }}
          />
        ))}
      </div>
    </div>
  );
}
