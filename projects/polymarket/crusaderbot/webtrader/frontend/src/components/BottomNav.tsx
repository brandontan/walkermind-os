import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/dashboard", label: "Dashboard", icon: "⊞" },
  { to: "/autotrade", label: "Auto Trade", icon: "⚡" },
  { to: "/portfolio", label: "Portfolio", icon: "📈" },
  { to: "/wallet", label: "Wallet", icon: "💰" },
  { to: "/settings", label: "Settings", icon: "⚙" },
] as const;

export function BottomNav() {
  return (
    <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-mobile border-t border-border bg-card z-50">
      <div className="flex">
        {TABS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex flex-col items-center justify-center flex-1 py-2 text-xs gap-1 transition-colors ${
                isActive ? "text-amber" : "text-muted"
              }`
            }
          >
            <span className="text-lg leading-none">{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
