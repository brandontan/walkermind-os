import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/dashboard",  label: "Dashboard",  icon: "🏠" },
  { to: "/autotrade",  label: "Auto Trade", icon: "⚡" },
  { to: "/portfolio",  label: "Portfolio",  icon: "📊" },
  { to: "/wallet",     label: "Wallet",     icon: "💰" },
  { to: "/settings",   label: "Settings",   icon: "⚙️" },
] as const;

export function BottomNav() {
  return (
    <nav
      className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-mobile border-t border-border z-50"
      style={{ backdropFilter: "blur(12px)", background: "rgba(13,17,23,0.85)" }}
    >
      <div className="flex">
        {TABS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `relative flex flex-col items-center justify-center flex-1 py-3 text-xs gap-1 transition-colors ${
                isActive ? "text-gold" : "text-muted hover:text-primary"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span
                    className="absolute top-0 left-1/2 -translate-x-1/2 rounded-full bg-gold"
                    style={{ width: "20px", height: "2px" }}
                  />
                )}
                <span className="text-lg leading-none">{icon}</span>
                <span className="font-medium">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
