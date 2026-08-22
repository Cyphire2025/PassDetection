import type { BrowserAttendanceQueueSafetySnapshot } from "@/features/tour-operations/services/attendance-queue-safety-contract";

const QUEUE_SAFE_SIGN_OUT_REQUIRED_EVENT =
  "passdetection:queue-safe-sign-out-required";

export function requestQueueSafeSignOutReview(
  snapshot: BrowserAttendanceQueueSafetySnapshot,
) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(QUEUE_SAFE_SIGN_OUT_REQUIRED_EVENT, {
    detail: snapshot,
  }));
}

export function subscribeToQueueSafeSignOutReview(
  listener: (snapshot: BrowserAttendanceQueueSafetySnapshot) => void,
) {
  if (typeof window === "undefined") return () => undefined;
  const handleReview = (event: Event) => {
    const snapshot = (event as CustomEvent<BrowserAttendanceQueueSafetySnapshot>).detail;
    if (snapshot?.ownerUserId) listener(snapshot);
  };
  window.addEventListener(QUEUE_SAFE_SIGN_OUT_REQUIRED_EVENT, handleReview);
  return () => window.removeEventListener(
    QUEUE_SAFE_SIGN_OUT_REQUIRED_EVENT,
    handleReview,
  );
}
