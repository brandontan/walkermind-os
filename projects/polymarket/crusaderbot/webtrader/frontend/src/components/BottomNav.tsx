import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/dashboard", label: "Home",   icon: "🏠" },
  { to: "/autotrade", label: "Auto",   icon: "🤖" },
  { to: "/portfolio", label: "Folio",  icon: "📊" },
  { to: "/wallet",    label: "Wallet", icon: "💰" },
  { to: "/settings",  label: "Config", icon: "⚙️" },
] as const;

export function BottomNav() {
  return (
    <nav
      className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-mobile z-[100] border-t border-border-2 grid grid-cols-5 pt-2 pb-3"
      style={{
        background: "rgba(2,5,11,0.95)",
        backdropFilter: "blur(24px) saturate(180%)",
        WebkitBackdropFilter: "blur(24px) saturate(180%)",
      }}
    >
      {/* HUD bracket markers on top edge */}
      <span
        className="absolute left-0 -top-px h-px w-6 bg-gold pointer-events-none"
        style={{ boxShadow: "0 0 8px var(--gold,#F5C842)" }}
        aria-hidden
      />
      <span
        className="absolute right-0 -top-px h-px w-6 bg-gold pointer-events-none"
        style={{ boxShadow: "0 0 8px var(--gold,#F5C842)" }}
        aria-hidden
      />
      {TABS.map(({ to, label, icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `relative flex flex-col items-center gap-[3px] py-1.5 cursor-pointer transition-all ${
              isActive ? "" : ""
            }`
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <span
                  className="absolute -top-2 left-1/2 -translate-x-1/2 w-[30%] h-0.5 bg-gold pointer-events-none"
                  style={{ boxShadow: "0 0 12px var(--gold,#F5C842)" }}
                  aria-hidden
                />
              )}
              <span
                className="text-[18px] transition-all"
                style={{
                  opacity: isActive ? 1 : 0.5,
                  filter: isActive ? "grayscale(0%)" : "grayscale(80%)",
                  transform: isActive ? "translateY(-2px)" : "translateY(0)",
                }}
              >
                {icon}
              </span>
              <span
                className={`font-hud text-[8px] font-bold tracking-[1.5px] uppercase transition-colors ${
                  isActive ? "text-gold" : "text-ink-3"
                }`}
              >
                {label}
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
