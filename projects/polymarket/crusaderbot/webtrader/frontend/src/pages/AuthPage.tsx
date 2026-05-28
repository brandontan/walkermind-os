import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TelegramAuth } from "../components/TelegramAuth";
import { useAuth } from "../lib/auth";
import { apiLoginEmail, apiRegisterEmail } from "../lib/api";

type AuthTab = "telegram" | "email";
type EmailMode = "login" | "register";

export function AuthPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState<AuthTab>("telegram");
  // Within the email tab: login vs register sub-mode. The two are mutually
  // exclusive — only the active mode's form is visible. Switch via the bottom
  // link inside the form ("No account? Register" / "Already registered? Sign in").
  const [emailMode, setEmailMode] = useState<EmailMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) navigate("/dashboard", { replace: true });
  }, [user, navigate]);

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = emailMode === "register"
        ? await apiRegisterEmail(email.trim(), password, firstName.trim())
        : await apiLoginEmail(email.trim(), password);
      login(res.access_token, res.user_id, res.first_name);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Authentication failed";
      // Strip status code prefix for cleaner display
      setError(msg.replace(/^\d+:\s*/, ""));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 animate-page-in">
      <div className="w-full max-w-[400px] text-center">

        {/* Brand — full wordmark logo (text baked in) */}
        <div className="mb-8">
          <img
            src={`${import.meta.env.BASE_URL}crusaderbot-wordmark.png`}
            alt="CrusaderBot — Built for Battle, Programmed to Protect"
            width={300}
            height={200}
            className="rounded-2xl"
            style={{
              objectFit: "contain",
              filter: "drop-shadow(0 0 24px rgba(245,200,66,0.25))",
              margin: "0 auto",
              display: "block",
              maxWidth: "100%",
            }}
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
        </div>

        {/* HUD-styled login card */}
        <div
          className="relative px-6 py-7 mb-5 clip-card-lg border border-border-2"
          style={{
            background:
              "radial-gradient(circle at 80% 0%, rgba(245,200,66,0.10) 0%, transparent 50%), linear-gradient(170deg, #0E1830 0%, #0A1322 50%, #060B16 100%)",
          }}
        >
          <Cross className="top-2 left-2" pos="tl" />
          <Cross className="top-2 right-2" pos="tr" />
          <Cross className="bottom-2 left-2" pos="bl" />
          <Cross className="bottom-2 right-2" pos="br" />

          <div className="font-hud text-[10px] tracking-[2.5px] uppercase text-gold mb-4">
            <span>◢ </span>Authentication Required
          </div>

          {/* Tab switcher — only 2 top-level tabs (Telegram | Email).
              Within Email, the bottom link inside the form switches between
              login and register modes so the user never sees both at once. */}
          <div className="flex gap-1 mb-5 bg-surface-2 rounded p-0.5">
            {(["telegram", "email"] as AuthTab[]).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError(null); }}
                className={[
                  "flex-1 text-[10px] font-hud tracking-widest uppercase py-1.5 rounded transition-all",
                  tab === t
                    ? "bg-gold text-black font-bold"
                    : "text-ink-3 hover:text-ink-1",
                ].join(" ")}
              >
                {t === "telegram" ? "Telegram" : "Email"}
              </button>
            ))}
          </div>

          {/* Telegram tab */}
          {tab === "telegram" && (
            <>
              <p className="text-ink-2 text-[13px] mb-5 leading-[1.4]">
                Sign in with your Telegram account to access your tactical dashboard.
              </p>
              <div className="flex justify-center">
                <TelegramAuth />
              </div>
              <p className="text-ink-3 text-[11px] mt-5 font-sans">
                No Telegram?{" "}
                <button
                  className="text-gold underline-offset-2 hover:underline"
                  onClick={() => { setTab("email"); setEmailMode("register"); setError(null); }}
                >
                  Register with email
                </button>
              </p>
            </>
          )}

          {/* Email tab — single form, login OR register based on emailMode.
              Never both visible at once. */}
          {tab === "email" && (
            <form onSubmit={(e) => void handleEmailSubmit(e)} className="text-left space-y-3">
              <div className="text-center mb-1">
                <span className="font-hud text-[12px] font-bold tracking-[2px] uppercase text-ink-1">
                  {emailMode === "register" ? "Create Account" : "Sign In"}
                </span>
              </div>
              {emailMode === "register" && (
                <div>
                  <label className="block text-[10px] font-hud tracking-widest uppercase text-ink-3 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Your name"
                    required
                    className="w-full bg-surface-2 border border-border-2 rounded px-3 py-2 text-[13px] text-ink-1 placeholder:text-ink-4 focus:outline-none focus:border-gold"
                  />
                </div>
              )}
              <div>
                <label className="block text-[10px] font-hud tracking-widest uppercase text-ink-3 mb-1">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  className="w-full bg-surface-2 border border-border-2 rounded px-3 py-2 text-[13px] text-ink-1 placeholder:text-ink-4 focus:outline-none focus:border-gold"
                />
              </div>
              <div>
                <label className="block text-[10px] font-hud tracking-widest uppercase text-ink-3 mb-1">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={emailMode === "register" ? "Min 8 characters" : "Password"}
                  required
                  minLength={8}
                  className="w-full bg-surface-2 border border-border-2 rounded px-3 py-2 text-[13px] text-ink-1 placeholder:text-ink-4 focus:outline-none focus:border-gold"
                />
              </div>

              {error && (
                <p className="text-red-400 text-[11px] font-mono">{error}</p>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 mt-1 bg-gold text-black font-hud text-[11px] tracking-widest uppercase rounded hover:bg-gold/90 disabled:opacity-50 transition-all"
              >
                {loading ? "…" : emailMode === "register" ? "Create Account" : "Sign In"}
              </button>

              <p className="text-ink-3 text-[11px] text-center font-sans pt-1">
                {emailMode === "login" ? (
                  <>No account?{" "}
                    <button type="button" className="text-gold hover:underline" onClick={() => { setEmailMode("register"); setError(null); }}>
                      Register
                    </button>
                  </>
                ) : (
                  <>Already registered?{" "}
                    <button type="button" className="text-gold hover:underline" onClick={() => { setEmailMode("login"); setError(null); }}>
                      Sign in
                    </button>
                  </>
                )}
              </p>
            </form>
          )}
        </div>

        <p className="text-ink-4 text-[10px] mt-2 font-mono tracking-[1.5px] uppercase">
          <span className="text-gold">◢</span> Secure channel · Tactical sim active
        </p>

        <p className="text-ink-3 text-[11px] mt-4 font-sans">
          By continuing you agree to our{" "}
          <a
            href="/legal/terms"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gold hover:underline"
          >
            Terms of Service
          </a>
          {" "}and{" "}
          <a
            href="/legal/privacy"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gold hover:underline"
          >
            Privacy Policy
          </a>
          . CrusaderBot is a trading aid, not financial advice — no profit is guaranteed.
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
