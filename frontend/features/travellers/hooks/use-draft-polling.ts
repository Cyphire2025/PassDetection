"use client";

import { useEffect } from "react";
const pollDelay = (completed: number) => completed < 5 ? 2000 : completed < 15 ? 5000 : 15000;

/** One request at a time, with a bounded window and no queued polling backlog. */
export function useDraftPolling(active: boolean, refresh: () => Promise<unknown>, report: (message: string) => void, cycle = "") {
  useEffect(() => {
    if (!active) return;
    let stopped = false, polls = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (stopped) return;
      if (!document.hidden) {
        if (++polls > 30) { report("The document check is taking longer than usual. Select Retry to check again."); return; }
        await refresh().catch(() => undefined);
      }
      if (!stopped) timer = setTimeout(() => void tick(), pollDelay(polls));
    };
    timer = setTimeout(() => void tick(), pollDelay(polls));
    return () => { stopped = true; clearTimeout(timer); };
  }, [active, refresh, report, cycle]);
}
