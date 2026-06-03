import { useCallback, useEffect, useRef, useState } from "react";
import type { FeedSignal, MarketFeedItem, RuntimeStatus } from "../lib/api";

/* ── tone map (mirrors Terminal.tsx) ──────────────────────────────────── */
type Tone = "cmd" | "ok" | "warn" | "out" | "dim";
const TONE: Record<Tone, string> = {
  cmd:  "text-cyan",
  ok:   "text-grn",
  warn: "text-gold",
  out:  "text-ink-2",
  dim:  "text-ink-3",
};

/* ── formatting helpers ───────────────────────────────────────────────── */
function fmtSecs(s: number): string {
  if (s <= 0) return "closing";
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s % 60}s`;
}
function fmtLiq(v: number): string {
  return v >= 1000 ? `$${(v / 1000).toFixed(0)}K` : `$${v}`;
}
function fmtAgo(iso: string): string {
  // Clamp at 0 — a client clock running behind the server would otherwise
  // render a future published_at as a negative "−5s ago".
  const d = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (d < 60) return `${Math.round(d)}s ago`;
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  return `${Math.round(d / 3600)}h ago`;
}

const LEAN_ARROW: Record<MarketFeedItem["lean"], string> = { UP: "▲", DOWN: "▼", EVEN: "─" };
const LEAN_VAR: Record<MarketFeedItem["lean"], string> = {
  UP:   "var(--grn,#00FF9C)",
  DOWN: "var(--red,#FF2D55)",
  EVEN: "var(--gold,#F5C842)",
};
const sideVar = (s: string) => (s.toUpperCase() === "YES" ? "var(--grn,#00FF9C)" : "var(--red,#FF2D55)");
const sideBg  = (s: string) => (s.toUpperCase() === "YES" ? "rgba(0,255,156,.12)" : "rgba(255,45,85,.12)");

/* ══════════════════════════════════════════════════════════════════════
   SIGNAL CAROUSEL — auto-advancing FeedSignal[] viewport
══════════════════════════════════════════════════════════════════════ */
function SignalCarousel({ signals }: { signals: FeedSignal[] }) {
  const [idx, setIdx] = useState(0);
  const [dir, setDir] = useState(1);
  const [animKey, setAnimKey] = useState(0);
  const [paused, setPaused] = useState(false);
  const prevLen = useRef(signals.length);

  // Reset to first card when the underlying list changes length (preset switch).
  useEffect(() => {
    if (prevLen.current !== signals.length) {
      prevLen.current = signals.length;
      setIdx(0);
      setDir(1);
      setAnimKey((k) => k + 1);
    }
  }, [signals.length]);

  const advance = useCallback((step: number) => {
    setDir(step);
    setIdx((i) => (i + step + signals.length) % signals.length);
    setAnimKey((k) => k + 1);
  }, [signals.length]);

  useEffect(() => {
    if (paused || signals.length <= 1) return;
    const t = setInterval(() => advance(1), 3800);
    return () => clearInterval(t);
  }, [paused, advance, signals.length]);

  if (!signals.length) return null;
  const sig = signals[Math.min(idx, signals.length - 1)];
  const targetCents = sig.target_price != null ? `${Math.round(sig.target_price * 100)}¢` : "—";

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      style={{ borderTop: "1px solid rgba(255,255,255,.04)" }}
    >
      {/* header row */}
      <div className="flex items-center justify-between px-3.5 pt-1.5 pb-1">
        <span className="font-hud text-[7px] font-bold tracking-[2px] uppercase text-ink-4">Signals</span>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-[3px]">
            {signals.map((_, i) => (
              <button
                type="button"
                key={i}
                aria-label={`Go to signal ${i + 1}`}
                onClick={() => { setDir(i > idx ? 1 : -1); setIdx(i); setAnimKey((k) => k + 1); }}
                className="h-1 rounded-full border-0 p-0 cursor-pointer transition-all duration-300"
                style={{ width: i === idx ? 10 : 4, background: i === idx ? "var(--gold,#F5C842)" : "var(--ink-4,#3D5278)" }}
              />
            ))}
          </div>
          <span className="font-mono text-[8px] text-gold">{idx + 1}/{signals.length}</span>
          {(["◂", "▸"] as const).map((arrow, i) => (
            <button
              type="button"
              key={arrow}
              aria-label={i === 0 ? "previous signal" : "next signal"}
              onClick={() => advance(i === 0 ? -1 : 1)}
              className="bg-transparent border-0 cursor-pointer text-ink-3 hover:text-gold text-[10px] leading-none px-px transition-colors"
            >
              {arrow}
            </button>
          ))}
        </div>
      </div>

      {/* viewport */}
      <div className="relative overflow-hidden">
        {!paused && (
          <div
            key={`pb-${animKey}`}
            className="absolute top-0 left-0 h-0.5"
            style={{ background: "linear-gradient(90deg,var(--gold,#F5C842),rgba(245,200,66,.3))", animation: "barProgress 3.8s linear forwards" }}
            aria-hidden
          />
        )}
        <div
          key={animKey}
          className="px-3.5 pt-2.5 pb-3"
          style={{ animation: `${dir > 0 ? "slideInRight" : "slideInLeft"} .32s cubic-bezier(.22,1,.36,1) both` }}
        >
          {/* top row */}
          <div className="flex items-center gap-2 mb-2.5">
            <span
              className="font-hud text-[9px] font-bold tracking-[1.5px] px-2 py-[3px] clip-tab flex-shrink-0"
              style={{ background: sideBg(sig.side), color: sideVar(sig.side) }}
            >
              {sig.side.toUpperCase()}
            </span>
            <span className="font-sans text-[13px] font-semibold text-ink-1 flex-1 min-w-0 truncate">
              {sig.market_question}
            </span>
            <span className="font-mono text-[10px] text-ink-3 flex-shrink-0">→{targetCents}</span>
            <span className="font-mono text-[9px] text-ink-4 flex-shrink-0">{fmtAgo(sig.published_at)}</span>
          </div>
          {/* detail grid */}
          <div className="grid grid-cols-3 gap-1.5">
            {[
              { label: "STRATEGY",  value: sig.signal_type,  cls: "text-cyan" },
              { label: "TARGET",    value: targetCents,      cls: "text-gold" },
              { label: "MARKET ID", value: sig.market_id,    cls: "text-ink-3" },
            ].map((f) => (
              <div key={f.label} className="px-2 py-1.5 clip-card-sm" style={{ background: "rgba(255,255,255,.025)" }}>
                <div className="font-hud text-[7px] font-bold tracking-[1.5px] uppercase text-ink-4 mb-0.5">{f.label}</div>
                <div className={`font-mono text-[10px] truncate ${f.cls}`}>{f.value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   SCANNER PANEL — RuntimeStatus + FeedSignal[] + MarketFeedItem[]
══════════════════════════════════════════════════════════════════════ */
const BASE_COUNT = 6;

type TLineDef = { parts: { type: Tone; text: string }[]; cursor?: boolean };

export type ScannerPanelProps = {
  runtime: RuntimeStatus | null;
  signals: FeedSignal[];
  feed: MarketFeedItem[];
  signalsToday: number;
  /** Bot/scanner active for this user (auto_trade_on && not halted). */
  active: boolean;
  tradingMode: string;
  activePreset: string | null;
  /** SSE-derived last tick (ms) — fallback when runtime.scanner_last_tick is null. */
  lastTickMs: number | null;
};

export function ScannerPanel({
  runtime, signals, feed, signalsToday, active, tradingMode, activePreset, lastTickMs,
}: ScannerPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const [visLines, setVisLines] = useState(0);
  const [, setTick] = useState(0); // 1s clock to keep liveAgo fresh
  const prevPreset = useRef(activePreset);

  // live 1s clock
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  // re-stagger the terminal lines whenever the preset changes
  useEffect(() => {
    if (prevPreset.current !== activePreset) {
      prevPreset.current = activePreset;
      setVisLines(0);
    }
  }, [activePreset]);

  // stagger lines in at 160ms after mount / reset — one timeout per line keeps
  // the updater pure (no side effects inside setState) and the deps honest.
  useEffect(() => {
    if (visLines >= BASE_COUNT) return;
    const t = setTimeout(() => setVisLines((v) => v + 1), 160);
    return () => clearTimeout(t);
  }, [visLines]);

  const lastTickSec = runtime?.scanner_last_tick ?? (lastTickMs != null ? lastTickMs / 1000 : null);
  const liveAgo = lastTickSec != null ? Math.max(0, Math.round(Date.now() / 1000 - lastTickSec)) : null;

  const scanned   = runtime?.scanner_scanned ?? 0;
  const published = runtime?.scanner_published ?? 0;

  const feedSummary = feed
    .map((f) => `${LEAN_ARROW[f.lean]} ${f.asset} ${Math.round(f.up_prob * 100)}%`)
    .join("  ");

  const lines: TLineDef[] = active
    ? [
        { parts: [{ type: "cmd", text: "market_signal_scanner" }, { type: "out", text: "  " }, { type: "ok", text: "✓ ok" }] },
        { parts: [{ type: "out", text: "mode " }, { type: "warn", text: tradingMode.toUpperCase() }, { type: "out", text: "  preset " }, { type: "cmd", text: activePreset ?? "none" }] },
        { parts: [{ type: "out", text: "scanned " }, { type: "warn", text: String(scanned) }, { type: "out", text: "  published " }, { type: "ok", text: String(published) }] },
        { parts: [{ type: "out", text: "last_tick " }, { type: "dim", text: `${liveAgo != null ? `${liveAgo}s ago` : "—"}  ` }, { type: "dim", text: "signals scanning" }], cursor: true },
        { parts: [{ type: "out", text: "markets  " }, { type: "dim", text: feedSummary || "—" }] },
        { parts: [{ type: "out", text: "status " }, { type: "dim", text: signals.length > 0 ? "signal_fired" : "awaiting_signal" }] },
      ]
    : [
        { parts: [{ type: "cmd", text: "market_signal_scanner" }, { type: "dim", text: "  ◦ idle" }] },
        { parts: [{ type: "out", text: "bot " }, { type: "warn", text: "OFF" }, { type: "out", text: "  mode " }, { type: "dim", text: tradingMode.toUpperCase() }] },
        { parts: [{ type: "out", text: "scanned " }, { type: "warn", text: String(scanned) }, { type: "out", text: "  published " }, { type: "ok", text: String(published) }] },
        { parts: [{ type: "out", text: "markets  " }, { type: "dim", text: feedSummary || "—" }] },
        { parts: [{ type: "out", text: "status " }, { type: "dim", text: "auto-trade disabled — enable from Auto tab" }], cursor: true },
        { parts: [{ type: "out", text: "last_tick " }, { type: "dim", text: liveAgo != null ? `${liveAgo}s ago` : "—" }] },
      ];

  return (
    <div
      className="relative mb-3 overflow-hidden clip-card border"
      style={{ background: "#0B1120", borderColor: "rgba(245,200,66,.2)" }}
    >
      {/* top gold line */}
      <span
        className="absolute top-0 left-0 right-0 h-px pointer-events-none"
        style={{ background: "linear-gradient(90deg,var(--gold,#F5C842),transparent 60%)" }}
        aria-hidden
      />

      {/* ── header ─────────────────────────────────────────── */}
      <div className="flex items-center gap-2.5 py-2.5 px-3.5 border-b border-border-1">
        <div className="flex gap-[5px]">
          {(["var(--red,#FF2D55)", "var(--gold,#F5C842)", "var(--grn,#00FF9C)"]).map((c, i) => (
            <span key={i} className="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ background: c, boxShadow: `0 0 5px ${c}` }} aria-hidden />
          ))}
        </div>
        <span className="font-mono text-[10px] tracking-[1px] text-ink-3 flex-1">scanner@crusaderbot</span>
        <span className={`flex items-center gap-1.5 font-hud text-[9px] font-bold tracking-[2px] ${active ? "text-grn" : "text-ink-3"}`}>
          <span
            className={`w-[7px] h-[7px] rounded-full inline-block flex-shrink-0 ${active ? "animate-status-pulse" : ""}`}
            style={{ background: active ? "var(--grn,#00FF9C)" : "var(--ink-3,#455370)", boxShadow: active ? "0 0 7px var(--grn,#00FF9C)" : "none" }}
            aria-hidden
          />
          {active ? "RUNNING" : "IDLE"}
        </span>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-label={expanded ? "collapse scanner" : "expand scanner"}
          aria-expanded={expanded}
          className="bg-transparent border-0 cursor-pointer font-hud text-[10px] text-ink-4 px-0.5 leading-none ml-1.5"
        >
          {expanded ? "▾" : "▸"}
        </button>
      </div>

      {expanded && (
        <>
          {/* ── stats row ─────────────────────────────────── */}
          <div className="grid grid-cols-3 border-b border-border-1">
            {[
              { label: "SCANNED",   value: scanned,   cls: "text-gold" },
              { label: "PUBLISHED", value: published, cls: "text-gold" },
              { label: "LAST TICK", value: liveAgo != null ? `${liveAgo}s ago` : "—", cls: liveAgo != null && liveAgo < 10 ? "text-grn" : "text-gold" },
            ].map((s, i) => (
              <div key={s.label} className={`py-1.5 px-2.5 text-center ${i < 2 ? "border-r border-border-1" : ""}`}>
                <div className="font-hud text-[7px] font-bold tracking-[2px] uppercase text-ink-4 mb-0.5">{s.label}</div>
                <div className={`font-mono text-[13px] font-bold ${s.cls}`}>{s.value}</div>
              </div>
            ))}
          </div>

          {/* ── sweep bar ─────────────────────────────────── */}
          <div
            className="relative h-5 overflow-hidden flex items-center px-3.5 gap-2 border-b border-border-1"
            style={{ background: "rgba(0,255,156,.015)" }}
          >
            <div
              className="absolute top-0 h-full pointer-events-none animate-scan-sweep"
              style={{ width: "18%", background: "linear-gradient(90deg,transparent,rgba(0,255,156,.15),rgba(0,255,156,.28),rgba(0,255,156,.15),transparent)" }}
              aria-hidden
            />
            <span className="relative z-[1] font-hud text-[7px] font-bold tracking-[2.5px] uppercase text-grn">SCANNING</span>
            <div
              className="relative z-[1] flex-1 h-px"
              style={{ background: "repeating-linear-gradient(90deg,rgba(0,255,156,.12) 0,rgba(0,255,156,.12) 2px,transparent 2px,transparent 8px)" }}
              aria-hidden
            />
            <span className="relative z-[1] font-mono text-[8px] text-ink-4">{signalsToday} signals today</span>
          </div>

          {/* ── terminal lines (staggered) ────────────────── */}
          <div className="px-4 pt-3 pb-2.5 font-mono text-[12px] leading-[1.85] border-b border-border-1">
            {lines.map((l, i) => (
              <div
                key={i}
                className="flex gap-2 items-baseline min-h-[20px]"
                style={{ animation: "signalIn .22s both", display: visLines > i ? undefined : "none" }}
              >
                <span className="text-cyan flex-shrink-0 select-none font-medium">›</span>
                <span className="break-all">
                  {l.parts.map((p, j) => (
                    <span key={j} className={TONE[p.type]}>{p.text}</span>
                  ))}
                  {l.cursor && <span className="animate-blink inline-block w-[7px] h-[0.85em] align-middle ml-0.5 bg-gold" aria-hidden />}
                </span>
              </div>
            ))}
          </div>

          {/* ── market rows ───────────────────────────────── */}
          {feed.length > 0 && (
            <div className="border-b border-border-1">
              <div className="flex items-center justify-between px-3.5 pt-1.5 pb-1">
                <span className="font-hud text-[7px] font-bold tracking-[2px] uppercase text-ink-4">Markets</span>
                <span className="font-mono text-[8px] text-ink-4">prob · countdown · liquidity</span>
              </div>
              {feed.map((it) => {
                const pct = Math.round(it.up_prob * 100);
                const c = LEAN_VAR[it.lean];
                return (
                  <div key={it.asset} className="flex items-center gap-2 px-3.5 py-1" style={{ borderTop: "1px solid rgba(255,255,255,.03)" }}>
                    <span className="font-hud text-[8px] font-bold tracking-[1.5px] text-ink-3 w-[38px] flex-shrink-0">{it.asset}</span>
                    <span className="font-mono text-[11px] font-bold w-3.5 flex-shrink-0" style={{ color: c }}>{LEAN_ARROW[it.lean]}</span>
                    <div className="flex-1 relative h-[3px]" style={{ background: "rgba(255,255,255,.06)" }}>
                      <div className="absolute left-0 top-0 h-full transition-all duration-700" style={{ width: `${pct}%`, background: c, boxShadow: `0 0 4px ${c}` }} />
                    </div>
                    <span className="font-mono text-[10px] font-bold w-8 text-right flex-shrink-0" style={{ color: c }}>{pct}%</span>
                    <span className="font-mono text-[9px] text-ink-4 w-[46px] text-right flex-shrink-0">{fmtSecs(it.seconds_to_close)}</span>
                    <span className="font-mono text-[9px] text-ink-4 w-[38px] text-right flex-shrink-0">{fmtLiq(it.liquidity_usdc)}</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* ── signal carousel ───────────────────────────── */}
          <SignalCarousel signals={signals} />
        </>
      )}

      {/* collapsed strip */}
      {!expanded && (
        <div className="flex items-center gap-2 px-3.5 py-1.5">
          <span
            className={`w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 ${active ? "animate-status-pulse" : ""}`}
            style={{ background: active ? "var(--grn,#00FF9C)" : "var(--ink-3,#455370)", boxShadow: active ? "0 0 6px var(--grn,#00FF9C)" : "none" }}
            aria-hidden
          />
          <span className="font-mono text-[10px] tracking-[1px] text-ink-2">
            {scanned} scanned · {published} published
          </span>
          <span className="ml-auto font-mono text-[9px] text-gold">{signalsToday} signals</span>
        </div>
      )}
    </div>
  );
}
