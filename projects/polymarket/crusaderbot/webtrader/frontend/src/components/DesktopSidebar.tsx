import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSSEStatus } from "../lib/sse";
import { useAuth } from "../lib/auth";
import { makeApi } from "../lib/api";

const MAIN_NAV = [
  { to: "/dashboard",  label: "Dashboard",  icon: "🏠" },
  { to: "/autotrade",  label: "Auto Trade", icon: "🤖", sub: { to: "/autotrade?tab=copy", label: "↳ Copy Trade" } },
  { to: "/portfolio",  label: "Portfolio",  icon: "📊" },
  { to: "/wallet",     label: "Wallet",     icon: "💰" },
] as const;

export function DesktopSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const sseConnected = useSSEStatus();
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [confirming, setConfirming] = useState(false);
  // Pull the user's auto_trade_on state so the System Status block can
  // reflect whether the user's bot is actually running, not just the
  // global scheduler. Polled every 30s so a toggle from Auto tab
  // propagates here without a full reload.
  const [autoOn, setAutoOn] = useState<boolean | null>(null);
  // Mirror AutoTradePage: when the operator has globally disabled copy_trade
  // the "↳ Copy Trade" sidebar subitem is hidden so it cannot send the user
  // to a tab that will just bounce back. FAIL-SAFE: until the availability
  // fetch completes (or on a fetch error) the entry stays visible.
  const [copyTradeEnabled, setCopyTradeEnabled] = useState(true);
  useEffect(() => {
    if (!user?.token) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const [dash, avail] = await Promise.allSettled([
          api.getDashboard(),
          api.getPresetAvailability(),
        ]);
        if (cancelled) return;
        if (dash.status === "fulfilled") setAutoOn(dash.value.auto_trade_on);
        else setAutoOn(null);
        if (avail.status === "fulfilled") {
          setCopyTradeEnabled(avail.value.strategies?.copy_trade !== false);
        }
      } catch {
        if (!cancelled) setAutoOn(null);
      }
    };
    void tick();
    const id = setInterval(() => void tick(), 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [api, user?.token]);
  const [stopping, setStopping] = useState(false);

  async function handleEmergencyStop() {
    setStopping(true);
    try {
      await api.postEmergencyStop();
      navigate("/dashboard");
    } finally {
      setStopping(false);
      setConfirming(false);
    }
  }

  const isActive = (to: string) => location.pathname === to || location.pathname.startsWith(to + "/");

  return (
    <aside
      className="hidden md:flex fixed top-0 left-0 bottom-0 w-[180px] lg:w-[220px] flex-col z-[150] overflow-y-auto py-5"
      style={{
        background: "rgba(2,5,11,0.98)",
        borderRight: "1px solid rgba(245,200,66,0.14)",
      }}
    >
      {/* Brand header */}
      <div className="px-4 pb-4 mb-2" style={{ borderBottom: "1px solid rgba(245,200,66,0.08)" }}>
        <div className="flex items-center gap-2.5">
          <img
            src={`${import.meta.env.BASE_URL}crusaderbot-emblem.png`}
            alt="CrusaderBot"
            width={26}
            height={31}
            className="flex-shrink-0 object-contain"
            style={{ filter: "drop-shadow(0 0 8px rgba(245,200,66,0.4))" }}
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
          <div className="leading-none">
            <div className="font-display text-[13px] tracking-[1.5px] text-ink-1 uppercase">
              CRUSADER<span className="text-gold">BOT</span>
            </div>
            <div className="font-mono text-[7px] tracking-[2px] text-ink-4 uppercase mt-[2px]">
              TACTICAL · PAPER
            </div>
          </div>
        </div>
      </div>

      {/* Main nav section */}
      <div className="mb-5">
        <div
          className="font-mono text-[8px] font-bold tracking-[2.5px] text-ink-4 uppercase px-4 pb-2 mb-1"
          style={{ borderBottom: "1px solid rgba(245,200,66,0.06)" }}
        >
          Navigation
        </div>
        {MAIN_NAV.map((item) => {
          const active = isActive(item.to);
          const copyActive = location.pathname === "/copy-trade" || location.search.includes("tab=copy");
          return (
            <div key={item.to}>
              <button
                onClick={() => navigate(item.to)}
                className={[
                  "w-full flex items-center gap-2.5 px-4 py-2.5 text-left font-sans text-[14px] font-semibold transition-all duration-150",
                  "border-l-2",
                  active
                    ? "text-gold border-gold"
                    : "text-ink-3 border-transparent hover:text-ink-2",
                ].join(" ")}
                style={active ? { background: "rgba(245,200,66,0.06)" } : {}}
              >
                <span className="text-[15px] w-5 text-center flex-shrink-0">{item.icon}</span>
                {item.label}
              </button>
              {"sub" in item && item.sub && copyTradeEnabled && (
                <button
                  onClick={() => navigate(item.sub!.to)}
                  className={[
                    "w-full flex items-center gap-2 pl-10 pr-4 py-1.5 text-left font-sans text-[12px] font-medium transition-all duration-150 border-l-2",
                    copyActive
                      ? "text-gold border-gold"
                      : "text-ink-4 border-transparent hover:text-ink-3",
                  ].join(" ")}
                  style={copyActive ? { background: "rgba(245,200,66,0.04)" } : {}}
                >
                  {item.sub.label}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Divider */}
      <div className="h-px mx-4 mb-4" style={{ background: "rgba(245,200,66,0.06)" }} />

      {/* System section */}
      <div className="mb-5">
        <div
          className="font-mono text-[8px] font-bold tracking-[2.5px] text-ink-4 uppercase px-4 pb-2 mb-1"
          style={{ borderBottom: "1px solid rgba(245,200,66,0.06)" }}
        >
          System
        </div>
        <button
          onClick={() => navigate("/settings")}
          className={[
            "w-full flex items-center gap-2.5 px-4 py-2.5 text-left font-sans text-[14px] font-semibold transition-all duration-150",
            "border-l-2",
            isActive("/settings")
              ? "text-gold border-gold"
              : "text-ink-3 border-transparent hover:text-ink-2",
          ].join(" ")}
          style={isActive("/settings") ? { background: "rgba(245,200,66,0.06)" } : {}}
        >
          <span className="text-[15px] w-5 text-center flex-shrink-0">⚙️</span>
          Config
        </button>
        {!confirming ? (
          <button
            className="w-full flex items-center gap-2.5 px-4 py-2.5 text-left font-sans text-[14px] font-semibold transition-all duration-150 border-l-2 border-transparent hover:bg-[rgba(255,45,85,0.06)]"
            style={{ color: "var(--red, #FF2D55)" }}
            onClick={() => setConfirming(true)}
          >
            <span className="text-[15px] w-5 text-center flex-shrink-0">🛑</span>
            Emergency Stop
          </button>
        ) : (
          <div className="px-4 py-2.5">
            <p className="font-mono text-[9px] text-ink-3 leading-tight mb-2">
              Halt trading &amp; close ALL open positions at market — profit or loss.
            </p>
            <div className="flex gap-1.5">
              <button
                onClick={() => setConfirming(false)}
                disabled={stopping}
                className="flex-1 py-1.5 rounded-[2px] border border-border-2 text-ink-3 font-mono text-[9px] font-bold tracking-[1px] uppercase hover:text-ink-2 disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => void handleEmergencyStop()}
                disabled={stopping}
                className="flex-1 py-1.5 rounded-[2px] font-mono text-[9px] font-bold tracking-[1px] uppercase text-white disabled:opacity-60 transition-all"
                style={{ background: "var(--red, #FF2D55)" }}
              >
                {stopping ? "Stopping…" : "Stop All"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* System status card — pushed to bottom */}
      <div className="mt-auto px-3.5">
        <div
          className="p-3"
          style={{
            background: "var(--surface, #0D1322)",
            border: "1px solid rgba(245,200,66,0.06)",
            clipPath: "polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px)",
          }}
        >
          <div className="font-mono text-[8px] font-bold tracking-[2px] text-ink-3 uppercase mb-2.5 flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full animate-status-pulse flex-shrink-0"
              style={{
                background: sseConnected ? "var(--grn,#00FF9C)" : "var(--gold,#F5C842)",
                boxShadow: `0 0 6px ${sseConnected ? "var(--grn,#00FF9C)" : "var(--gold,#F5C842)"}`,
              }}
            />
            System Status
          </div>
          {[
            // SCANNER reflects the user's auto_trade_on, not the global
            // scheduler. When the user's bot is off, the scanner is
            // semantically IDLE for them. autoOn === null while we're
            // still fetching the first tick — fall back to RUNNING then.
            {
              label: "SCANNER",
              value: autoOn === false ? "IDLE" : "RUNNING",
              tone: autoOn === false ? "dim" : "grn",
            },
            { label: "MODE",    value: "PAPER",   tone: "blue" },
            { label: "GUARDS",  value: "LOCKED",  tone: "warn" },
          ].map(({ label, value, tone }) => (
            <div
              key={label}
              className="flex justify-between font-mono text-[9px] text-ink-3 py-[3px] tracking-[0.5px]"
            >
              <span>{label}</span>
              <span
                className="font-bold"
                style={{
                  color:
                    tone === "grn"  ? "var(--grn,#00FF9C)"  :
                    tone === "blue" ? "var(--blue,#4D9FFF)"  :
                    tone === "dim"  ? "var(--ink-3,#455370)" :
                                     "var(--gold,#F5C842)",
                }}
              >
                {value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
