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

    let es: EventSource;
    let reconnectTimeout: ReturnType<typeof setTimeout>;
    let backoff = 1000;
    let destroyed = false;

    function connect() {
      const url = `/api/web/stream?token=${encodeURIComponent(token!)}`;
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
        "portfolio_update", "scanner_tick",
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
        es.close();
        if (!destroyed) {
          reconnectTimeout = setTimeout(() => {
            backoff = Math.min(backoff * 2, 30_000);
            connect();
          }, backoff);
        }
      };
    }

    connect();

    return () => {
      destroyed = true;
      clearTimeout(reconnectTimeout);
      es?.close();
      setConnected(false);
    };
  }, [token]); // re-connect only when token changes

  return { connected };
}
