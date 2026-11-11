import { useEffect, useState } from "react";

/** Seconds remaining until an eviction deadline, floored at zero. */
function secondsLeft(deadline: string): number {
  const ms = Date.parse(deadline) - Date.now();
  return ms > 0 ? Math.ceil(ms / 1000) : 0;
}

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** How often the eviction countdown re-renders. Isolated into its own
 * component so ticking it doesn't re-render the whole page (and, in
 * particular, doesn't touch the noVNC viewer) every second. */
const COUNTDOWN_TICK_MS = 1000;

/** Ticking "time left" label for an eviction deadline. */
export function Countdown({ deadline }: { deadline: string }) {
  const [remaining, setRemaining] = useState(() => secondsLeft(deadline));

  useEffect(() => {
    setRemaining(secondsLeft(deadline));
    const id = setInterval(() => setRemaining(secondsLeft(deadline)), COUNTDOWN_TICK_MS);
    return () => clearInterval(id);
  }, [deadline]);

  return <>{mmss(remaining)}</>;
}
