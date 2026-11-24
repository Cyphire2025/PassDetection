import {
  LEGACY_WHATSAPP_BATCH_STORAGE_KEY, WHATSAPP_ACTIVITY_STORAGE_KEY,
  parseLegacyWhatsAppBatch, parseTrackedWhatsAppActivities, type TrackedWhatsAppActivity,
} from "../../utils/activity-tracking";

export function subscribeToClientEnvironment() {
  return () => undefined;
}

export function readInitialTrackedActivities(): TrackedWhatsAppActivity[] {
  if (typeof window === "undefined") return [];
  try {
    const currentRaw = window.sessionStorage.getItem(
      WHATSAPP_ACTIVITY_STORAGE_KEY,
    );
    const current = parseTrackedWhatsAppActivities(currentRaw);
    if (currentRaw !== null) return current;
    const legacy = parseLegacyWhatsAppBatch(
      window.sessionStorage.getItem(LEGACY_WHATSAPP_BATCH_STORAGE_KEY),
    );
    return legacy ? [legacy] : [];
  } catch {
    return [];
  }
}
