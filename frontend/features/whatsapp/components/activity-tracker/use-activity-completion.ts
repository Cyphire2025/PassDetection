"use client";

import { useEffect, type RefObject } from "react";
import type { DisplayedWhatsAppActivity } from "../../utils/activity-tracking";
import type { WhatsAppActivityTrackerValue } from "./context";

const SUCCESS_AUTO_DISMISS_MS = 12_000;

export function useActivityCompletion(
  activities: DisplayedWhatsAppActivity[],
  dismissActivity: WhatsAppActivityTrackerValue["dismissActivity"],
  completionTimersRef: RefObject<Map<string, number>>,
) {
  useEffect(() => {
    const completedSuccessfully = new Set(
      activities
        .filter(
          (activity) =>
            activity.kind !== "document"
            && activity.total > 0
            && activity.queued === 0
            && activity.failed === 0
            && activity.delivery_unknown === 0
            && !activity.refresh_error
            && Boolean(activity.status_counts)
            && (activity.status_counts?.delivered ?? 0) + (activity.status_counts?.read ?? 0) === activity.total,
        )
        .map((activity) => `${activity.kind}:${activity.activity_id}`),
    );

    for (const [key, timer] of completionTimersRef.current) {
      if (completedSuccessfully.has(key)) continue;
      window.clearTimeout(timer);
      completionTimersRef.current.delete(key);
    }

    for (const activity of activities) {
      const key = `${activity.kind}:${activity.activity_id}`;
      if (
        !completedSuccessfully.has(key)
        || completionTimersRef.current.has(key)
      ) {
        continue;
      }
      const timer = window.setTimeout(() => {
        completionTimersRef.current.delete(key);
        dismissActivity(activity.activity_id, activity.kind);
      }, SUCCESS_AUTO_DISMISS_MS);
      completionTimersRef.current.set(key, timer);
    }
  }, [activities, dismissActivity, completionTimersRef]);

  useEffect(
    () => () => {
      for (const timer of completionTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      completionTimersRef.current.clear();
    },
    [completionTimersRef],
  );
}
