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
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[360px] text-center">
        <div className="mb-8">
          <img
            src="/crusaderbot-logo.png"
            alt="CrusaderBot"
            width={80}
            height={80}
            style={{
              objectFit: "contain",
              filter: "drop-shadow(0 0 12px rgba(245,200,66,0.4))",
              margin: "0 auto 16px",
              display: "block",
            }}
          />
          <h1 className="text-3xl font-bold text-primary tracking-tight">
            Crusader<span className="text-amber">Bot</span>
          </h1>
          <p className="text-muted text-sm mt-2">Your Polymarket co-pilot</p>
        </div>

        <div className="bg-card border border-border rounded-2xl p-8">
          <p className="text-muted text-sm mb-6">
            Sign in with your Telegram account to access your dashboard.
          </p>
          <div className="flex justify-center">
            <TelegramAuth />
          </div>
          <p className="text-muted text-xs mt-6">
            Don&apos;t have an account?{" "}
            <span className="text-amber">Start the @CrusaderBot bot on Telegram first.</span>
          </p>
        </div>

        <p className="text-muted/50 text-xs mt-6">
          Paper trading mode — no real capital deployed.
        </p>
      </div>
    </div>
  );
}
