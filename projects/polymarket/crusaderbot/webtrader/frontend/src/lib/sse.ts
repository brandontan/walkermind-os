import { createContext, useContext, useEffect, useRef, useState } from "react";

export type SSEHandlers = Record<string, (data: unknown) => void>;

export const SSEStatusContext = createContext<boolean>(false);

export function useSSEStatus(): boolean {
  return useContext(SSEStatusContext);
}

export function useSSE(token: string | null, handlers: SSEHandlers): { connected: boolean } {
  const [connected, setConnected] = useState(false);

  // Keep a ref so event listeners always call the latest handler without reconnecting
  const handlersRef = useRef<SSEHandlers>(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  }); // no deps — update on every render

  useEffect(() => {
    if (!token) {
      setConnected(false);
      return;
    }

    let es: EventSource | undefined;
    let reconnectTimeout: ReturnType<typeof setTimeout>;
    let backoff = 1000;
    let destroyed = false;

    function scheduleReconnect() {
      if (destroyed) return;
      reconnectTimeout = setTimeout(() => {
        backoff = Math.min(backoff * 2, 30_000);
        void connect();
      }, backoff);
    }

    async function connect() {
      if (destroyed) return;
      // The main JWT must never ride in the EventSource URL (it lands in
      // proxy/access logs). Exchange it for a short-lived, SSE-scoped handshake
      // token first; a fresh one is minted on every (re)connect.
      let streamToken: string;
      try {
        const res = await fetch("/api/web/stream-token", {
          method: "POST",
          headers: { Authorization: `Bearer ${token!}` },
        });
        if (!res.ok) throw new Error(`stream-token ${res.status}`);
        streamToken = (await res.json()).token as string;
      } catch {
        setConnected(false);
        scheduleReconnect();
        return;
      }
      if (destroyed) return;

      const url = `/api/web/stream?token=${encodeURIComponent(streamToken)}`;
      es = new EventSource(url);

      es.addEventListener("connected", () => {
        backoff = 1000;
        setConnected(true);
      });

      // Route each known SSE event type through the ref so callers
      // always see the latest handler closures (fixes stale filter state).
      const EVENT_TYPES = [
        "orders", "fills", "positions", "settings",
        "system", "portfolio", "alerts",
        "position_opened", "position_closed",
        "position_updated",
        "portfolio_update", "scanner_tick",
        "copy_trade_executed",
      ] as const;

      for (const eventType of EVENT_TYPES) {
        es.addEventListener(eventType, (e: MessageEvent) => {
          try {
            handlersRef.current[eventType]?.(JSON.parse(e.data));
          } catch {
            // ignore malformed events
          }
        });
      }

      es.onerror = () => {
        setConnected(false);
        es?.close();
        scheduleReconnect();
      };
    }

    void connect();

    return () => {
      destroyed = true;
      clearTimeout(reconnectTimeout);
      es?.close();
      setConnected(false);
    };
  }, [token]); // re-connect only when token changes

  return { connected };
}
