import { useLocation, useNavigate } from "react-router-dom";
import { AdvancedOnly } from "./AdvancedGate";
import { useSSEStatus } from "../lib/sse";

const TOPNAV = [
  { to: "/dashboard",  label: "Home" },
  { to: "/autotrade",  label: "Auto Trade" },
  { to: "/portfolio",  label: "Portfolio" },
  { to: "/wallet",     label: "Wallet" },
  { to: "/settings",   label: "Config" },
] as const;

type Props = {
  notifCount?: number;
  onBellClick?: () => void;
};

export function TopBar({ notifCount = 0, onBellClick }: Props) {
  const sseConnected = useSSEStatus();
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <div
      className="sticky top-0 z-[100] flex items-center justify-between px-4 pt-3.5 pb-3 border-b border-border-1 relative"
      style={{
        background: "rgba(2,5,11,0.92)",
        backdropFilter: "blur(20px) saturate(180%)",
        WebkitBackdropFilter: "blur(20px) saturate(180%)",
      }}
    >
      {/* HUD bracket markers on bottom edge */}
      <span
        className="absolute left-0 -bottom-px h-px w-6 bg-gold"
        style={{ boxShadow: "0 0 8px var(--gold, #F5C842)" }}
        aria-hidden
      />
      <span
        className="absolute right-0 -bottom-px h-px w-6 bg-gold"
        style={{ boxShadow: "0 0 8px var(--gold, #F5C842)" }}
        aria-hidden
      />

      {/* Brand */}
      <div className="flex items-center gap-2.5">
        <img
          src="/crusaderbot-logo.png"
          alt="CrusaderBot"
          width={44}
          height={50}
          className="flex-shrink-0 object-contain"
          style={{ filter: "drop-shadow(0 0 10px rgba(245,200,66,0.45))" }}
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
        <div className="leading-none">
          <div className="font-display text-[18px] tracking-[1.5px] text-ink-1 uppercase">
            CRUSADER<span className="text-gold">BOT</span>
          </div>
          <AdvancedOnly>
            <div
              className="font-mono text-[8px] tracking-[2.5px] text-ink-3 uppercase mt-[3px]"
              style={{ marginTop: "3px" }}
            >
              <span className="text-gold">◢ </span>TACTICAL · POLYMARKET
            </div>
          </AdvancedOnly>
        </div>
      </div>

      {/* Desktop center topnav pills — hidden on mobile */}
      <div className="hidden md:flex items-center gap-0.5 absolute left-1/2 -translate-x-1/2">
        {TOPNAV.map(({ to, label }) => {
          const active = location.pathname === to || location.pathname.startsWith(to + "/");
          return (
            <button
              key={to}
              onClick={() => navigate(to)}
              className={[
                "font-mono text-[9.5px] font-bold tracking-[1.5px] uppercase",
                "px-3 py-1.5 rounded-[2px] border transition-all duration-200 whitespace-nowrap cursor-pointer",
                active
                  ? "text-gold border-border-2 bg-[rgba(245,200,66,0.08)]"
                  : "text-ink-3 border-transparent hover:text-ink-2 hover:bg-[rgba(245,200,66,0.04)]",
              ].join(" ")}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-1.5">
        <span
          className="w-2 h-2 rounded-full flex-shrink-0"
          style={sseConnected
            ? { background: "var(--grn,#00FF9C)", boxShadow: "0 0 6px var(--grn,#00FF9C)" }
            : { background: "var(--red,#FF4444)", boxShadow: "0 0 6px var(--red,#FF4444)" }}
          title={sseConnected ? "Live stream connected" : "Reconnecting…"}
          aria-label={sseConnected ? "Stream connected" : "Stream reconnecting"}
        />
        <StatusPill kind="paper">PAPER</StatusPill>
        <AdvancedOnly>
          <StatusPill kind="live">
            <span className="inline-block w-[5px] h-[5px] rounded-full bg-current animate-status-pulse"
              style={{ boxShadow: "0 0 8px currentColor" }} aria-hidden />
            LIVE
          </StatusPill>
        </AdvancedOnly>
        <button
          onClick={onBellClick}
          className="relative w-8 h-8 rounded-[4px] bg-surface border border-border-2 flex items-center justify-center text-[13px] transition-colors hover:border-gold hover:bg-surface-2"
          aria-label="Notifications"
        >
          🔔
          {notifCount > 0 && (
            <span
              className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-gold text-bg-0 font-mono text-[8px] font-bold flex items-center justify-center"
              style={{ boxShadow: "0 0 8px rgba(245,200,66,0.5)" }}
            >
              {notifCount > 9 ? "9+" : notifCount}
            </span>
          )}
        </button>
      </div>
    </div>
  );
}

function StatusPill({
  kind,
  children,
}: {
  kind: "live" | "paper";
  children: React.ReactNode;
}) {
  const base =
    "inline-flex items-center gap-[5px] py-1 pl-2 pr-[9px] font-mono text-[9px] font-bold tracking-[1.5px]";
  const styles =
    kind === "live"
      ? { background: "rgba(0,255,156,0.08)", border: "1px solid rgba(0,255,156,0.3)", color: "var(--grn,#00FF9C)" }
      : { background: "rgba(245,200,66,0.08)", border: "1px solid rgba(245,200,66,0.3)", color: "var(--gold,#F5C842)" };
  return (
    <span
      className={`${base} clip-card-sm`}
      style={styles}
    >
      {children}
    </span>
  );
}
