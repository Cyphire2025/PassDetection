"use client";

import { createContext, useContext } from "react";
import type { DisplayedWhatsAppActivity, TrackedWhatsAppActivity } from "../../utils/activity-tracking";

export interface WhatsAppActivityTrackerValue {
  activities: DisplayedWhatsAppActivity[];
  registerActivity: (activity: TrackedWhatsAppActivity) => void;
  dismissActivity: (activityId: string, kind: TrackedWhatsAppActivity["kind"]) => void;
}

export const WhatsAppActivityTrackerContext =
  createContext<WhatsAppActivityTrackerValue | null>(null);

export function useWhatsAppActivityTracker(): WhatsAppActivityTrackerValue {
  const context = useContext(WhatsAppActivityTrackerContext);
  if (!context) {
    throw new Error(
      "useWhatsAppActivityTracker must be used inside WhatsAppActivityTrackerProvider",
    );
  }
  return context;
}
