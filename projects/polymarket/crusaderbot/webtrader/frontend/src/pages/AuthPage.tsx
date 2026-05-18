import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { TelegramAuth } from "../components/TelegramAuth";
import { useAuth } from "../lib/auth";

export function AuthPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (user) navigate("/dashboard", { replace: true });
  }, [user, navigate]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 animate-page-in">
      <div className="w-full max-w-[400px] text-center">

        {/* Brand */}
        <div className="mb-8">
          <img
            src="/crusaderbot-logo.png"
            alt="CrusaderBot"
            width={88}
            height={100}
            style={{
              objectFit: "contain",
              filter: "drop-shadow(0 0 12px rgba(245,200,66,0.5))",
              margin: "0 auto 18px",
              display: "block",
            }}
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
          <div className="font-display text-[32px] tracking-[1.5px] text-ink-1 uppercase leading-none">
            CRUSADER<span className="text-gold">BOT</span>
          </div>
          <div className="font-mono text-[8px] tracking-[2.5px] text-ink-3 uppercase mt-2">
            <span className="text-gold">◢ </span>TACTICAL · POLYMARKET
          </div>
        </div>

        {/* HUD-styled login card */}
        <div
          className="relative px-6 py-7 mb-5 clip-card-lg border border-border-2"
          style={{
            background:
              "radial-gradient(circle at 80% 0%, rgba(245,200,66,0.10) 0%, transparent 50%), linear-gradient(170deg, #0E1830 0%, #0A1322 50%, #060B16 100%)",
          }}
        >
          {/* Corner crosses */}
          <Cross className="top-2 left-2" pos="tl" />
          <Cross className="top-2 right-2" pos="tr" />
          <Cross className="bottom-2 left-2" pos="bl" />
          <Cross className="bottom-2 right-2" pos="br" />

          <div className="font-hud text-[10px] tracking-[2.5px] uppercase text-gold mb-3">
            <span>◢ </span>Authentication Required
          </div>
          <p className="text-ink-2 text-[13px] mb-5 leading-[1.4]">
            Sign in with your Telegram account to access your tactical dashboard.
          </p>
          <div className="flex justify-center">
            <TelegramAuth />
          </div>
          <p className="text-ink-3 text-[11px] mt-5 font-sans">
            Don&apos;t have an account?{" "}
            <span className="text-gold">Start @CrusaderBot on Telegram first.</span>
          </p>
        </div>

        <p className="text-ink-4 text-[11px] mt-2 font-mono tracking-[0.5px]">
          PAPER TRADING MODE — no real capital deployed
        </p>
      </div>
    </div>
  );
}

function Cross({ pos, className }: { pos: "tl" | "tr" | "bl" | "br"; className?: string }) {
  const borders: Record<typeof pos, string> = {
    tl: "1px 0 0 1px",
    tr: "1px 1px 0 0",
    bl: "0 0 1px 1px",
    br: "0 1px 1px 0",
  } as const;
  return (
    <span
      className={`absolute w-3.5 h-3.5 border-solid border-gold opacity-70 z-[2] ${className ?? ""}`}
      style={{ borderWidth: borders[pos] }}
      aria-hidden
    />
  );
}
