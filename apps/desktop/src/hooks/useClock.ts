import { useEffect, useState } from "react";

/** Live clock, independent of the backend and the LLM (PRD §6.1). Ticks on the minute boundary. */
export function useClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const d = new Date();
      setNow(d);
      timer = setTimeout(tick, 60_000 - (d.getSeconds() * 1000 + d.getMilliseconds()) + 20);
    };
    timer = setTimeout(tick, 60_000 - (now.getSeconds() * 1000 + now.getMilliseconds()) + 20);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return now;
}
