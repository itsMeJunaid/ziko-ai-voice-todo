import { useEffect } from "react";
import type { ServerEvent } from "../types";

/**
 * Live server events over the backend WebSocket (PRD §8.4), with capped exponential reconnect.
 * Event-driven updates replace polling (PRD §10.2).
 */
export function useEvents(wsUrl: string | null, onEvent: (e: ServerEvent) => void): void {
  useEffect(() => {
    if (!wsUrl) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const open = () => {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => (attempt = 0);
      ws.onmessage = (m) => {
        try {
          onEvent(JSON.parse(m.data) as ServerEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        const delay = Math.min(10_000, 500 * 2 ** attempt++);
        timer = setTimeout(open, delay);
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
    // onEvent is intentionally not a dependency: callers pass a stable store action wrapper.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsUrl]);
}
