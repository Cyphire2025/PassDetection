"use client";

import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { usePathname } from "next/navigation";
import { isWhatsAppBroadcastSourcePath } from "../utils/activity-tracking";
import { WhatsAppActivityTrackerContext } from "./activity-tracker/context";
import { DraggableWhatsAppActivityOverlay } from "./activity-tracker/floating-overlay";
import { useTrackedActivities } from "./activity-tracker/use-tracked-activities";

export { useWhatsAppActivityTracker } from "./activity-tracker/context";
export { WhatsAppActivityInline } from "./activity-tracker/inline";

export function WhatsAppActivityTrackerProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { contextValue, storageReady } = useTrackedActivities();
  const { activities, dismissActivity } = contextValue;
  const showFloatingTracker =
    storageReady
    && activities.length > 0
    && !isWhatsAppBroadcastSourcePath(pathname);
  return (
    <WhatsAppActivityTrackerContext.Provider value={contextValue}>
      {children}
      {showFloatingTracker
        ? createPortal(
            <DraggableWhatsAppActivityOverlay
              activities={activities}
              onDismiss={dismissActivity}
            />,
            document.body,
          )
        : null}
    </WhatsAppActivityTrackerContext.Provider>
  );
}
