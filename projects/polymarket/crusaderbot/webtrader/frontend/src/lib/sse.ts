import { useEffect, useRef } from "react";

export type SSEHandlers = Record<string, (data: unknown) => void>;

export function useSSE(token: string | null, handlers: SSEHandlers) {
  // Keep a ref so event listeners always call the latest handler without reconnecting
  const handlersRef = useRef<SSEHandlers>(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  }); // no deps — update on every render

  useEffect(() => {
    if (!token) return;

    let es: EventSource;
    let reconnectTimeout: ReturnType<typeof setTimeout>;
    let backoff = 1000;
    let destroyed = false;

    function connect() {
      const url = `/api/web/stream?token=${encodeURIComponent(token!)}`;
      es = new EventSource(url);

      es.addEventListener("connected", () => {
        backoff = 1000;
      });

      // Route each known SSE event type through the ref so callers
      // always see the latest handler closures (fixes stale filter state).
      const EVENT_TYPES = [
        "orders", "fills", "positions", "settings",
        "system", "portfolio", "alerts",
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
    };
  }, [token]); // re-connect only when token changes
}
