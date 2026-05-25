import { useLocation, useNavigate } from "react-router-dom";
import { useSSEStatus } from "../lib/sse";

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

  const isActive = (to: string) => location.pathname === to || location.pathname.startsWith(to + "/");

  return (
    <aside
      className="hidden md:flex fixed top-0 left-0 bottom-0 w-[180px] lg:w-[220px] flex-col z-[150] overflow-y-auto py-5"
      style={{
        background: "rgba(2,5,11,0.98)",
        borderRight: "1px solid rgba(245,200,66,0.14)",
      }}
    >
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
              {"sub" in item && item.sub && (
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
        <button
          className="w-full flex items-center gap-2.5 px-4 py-2.5 text-left font-sans text-[14px] font-semibold transition-all duration-150 border-l-2 border-transparent"
          style={{ color: "var(--red, #FF2D55)" }}
          onClick={() => navigate("/dashboard")}
        >
          <span className="text-[15px] w-5 text-center flex-shrink-0">🛑</span>
          Emergency Stop
        </button>
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
            { label: "SCANNER", value: "RUNNING", tone: "grn" },
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
