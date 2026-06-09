import { NavLink, useLocation } from "react-router-dom";

// ── SVG icon set — 20×20 stroke icons ────────────────────────────────────────
function IcoHome({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

function IcoAuto({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <circle cx="8.5" cy="11" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="11" r="1.5" fill="currentColor" stroke="none" />
      <path d="M8 15h8" />
    </svg>
  );
}

function IcoPortfolio({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
      <line x1="2" y1="20" x2="22" y2="20" />
    </svg>
  );
}

function IcoWallet({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4" />
      <path d="M3 5v14a2 2 0 0 0 2 2h16v-5" />
      <path d="M18 12a2 2 0 0 0 0 4h4v-4h-4z" />
    </svg>
  );
}

function IcoConfig({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
      <circle cx="8" cy="6" r="2" fill="currentColor" stroke="none" />
      <circle cx="16" cy="12" r="2" fill="currentColor" stroke="none" />
      <circle cx="10" cy="18" r="2" fill="currentColor" stroke="none" />
    </svg>
  );
}

// ── Nav items — Copy Trade lives inside Auto Trade (/autotrade?tab=copy) ──────
const TABS = [
  { to: "/dashboard",  label: "Home",   Icon: IcoHome      },
  { to: "/autotrade",  label: "Auto",   Icon: IcoAuto      },
  { to: "/portfolio",  label: "Port",   Icon: IcoPortfolio },
  { to: "/wallet",     label: "Wallet", Icon: IcoWallet    },
  { to: "/settings",   label: "Config", Icon: IcoConfig    },
] as const;

export function BottomNav() {
  const location = useLocation();

  // /copy-trade maps to the "Auto" tab for active-state purposes
  const effectivePath = location.pathname === "/copy-trade" ? "/autotrade" : location.pathname;

  return (
    <nav
      className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-mobile z-[100] border-t border-border-2 grid grid-cols-5 pt-2 pb-safe md:hidden"
      style={{
        background: "rgba(2,5,11,0.95)",
        backdropFilter: "blur(24px) saturate(180%)",
        WebkitBackdropFilter: "blur(24px) saturate(180%)",
        paddingBottom: "max(12px, env(safe-area-inset-bottom))",
      }}
    >
      {/* HUD bracket markers */}
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

      {TABS.map(({ to, label, Icon }) => {
        const isActive = effectivePath === to || effectivePath.startsWith(to + "/");
        return (
          <NavLink
            key={to}
            to={to}
            className="relative flex flex-col items-center gap-[3px] py-1.5 cursor-pointer transition-all"
            aria-label={label}
          >
            {isActive && (
              <span
                className="absolute -top-2 left-1/2 -translate-x-1/2 w-[30%] h-0.5 bg-gold pointer-events-none"
                style={{ boxShadow: "0 0 12px var(--gold,#F5C842)" }}
                aria-hidden
              />
            )}
            <span
              className="transition-all"
              style={{
                color: isActive ? "var(--gold,#F5C842)" : "var(--ink-3,#455370)",
                transform: isActive ? "translateY(-2px)" : "translateY(0)",
              }}
            >
              <Icon size={19} />
            </span>
            <span
              className="font-hud text-[8px] font-bold tracking-[1.5px] uppercase transition-colors"
              style={{ color: isActive ? "var(--gold,#F5C842)" : "var(--ink-3,#455370)" }}
            >
              {label}
            </span>
          </NavLink>
        );
      })}
    </nav>
  );
}
