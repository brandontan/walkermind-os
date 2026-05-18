import { useEffect, useRef } from "react";
import { useAuth } from "../lib/auth";

declare global {
  interface Window {
    onTelegramAuth?: (user: Record<string, unknown>) => void;
  }
}

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME ?? "CrusaderPolybot";

export function TelegramAuth() {
  const ref = useRef<HTMLDivElement>(null);
  const { login } = useAuth();

  useEffect(() => {
    window.onTelegramAuth = async (userData) => {
      try {
        const res = await fetch("/api/web/auth/telegram", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(userData),
        });
        if (!res.ok) throw new Error(`Auth failed: ${res.status}`);
        const { access_token, user_id, first_name } = await res.json() as {
          access_token: string;
          user_id: string;
          first_name: string;
        };
        login(access_token, user_id, first_name);
      } catch (err) {
        console.error("Telegram auth error:", err);
      }
    };

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", BOT_USERNAME);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    script.setAttribute("data-request-access", "write");
    script.async = true;
    ref.current?.appendChild(script);

    return () => {
      delete window.onTelegramAuth;
    };
  }, [login]);

  return <div ref={ref} />;
}
