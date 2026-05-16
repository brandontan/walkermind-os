import { useEffect } from "react";

export type SSEHandlers = Record<string, (data: unknown) => void>;

export function useSSE(token: string | null, handlers: SSEHandlers) {
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

      for (const [event, handler] of Object.entries(handlers)) {
        es.addEventListener(event, (e: MessageEvent) => {
          try {
            handler(JSON.parse((e as MessageEvent).data));
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
  }, [token]); // re-connect when token changes
}
