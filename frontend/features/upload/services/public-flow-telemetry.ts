export const VISA_PHOTO_REJECTION_REASONS = [
  "no_face",
  "multiple_faces",
  "too_far",
  "too_close",
  "off_center",
  "head_tilt",
  "eyewear_detected",
  "eyewear_uncertain",
  "too_dark",
  "too_bright",
  "blurry",
  "background_not_light_neutral",
  "background_not_plain",
  "camera_unavailable",
  "quality_model_unavailable",
] as const;

export const PASSPORT_SCANNER_REJECTION_REASONS = [
  "no_document",
  "incomplete_document",
  "too_small",
  "sideways",
  "upside_down",
  "excessive_skew",
  "multiple_documents",
  "screen_or_book",
  "missing_mrz",
  "not_passport_page",
  "glare",
  "too_dark",
  "too_bright",
  "blurry",
  "camera_unavailable",
  "crop_validation_failed",
] as const;

export const PUBLIC_FLOW_REASONS = [
  "connectivity_lost",
  "connectivity_restored",
  "camera_cancelled",
  "upload_abandoned",
  "recovery_started",
  "recovery_succeeded",
  "recovery_missed",
] as const;

export type VisaPhotoRejectionReason =
  typeof VISA_PHOTO_REJECTION_REASONS[number];
export type PassportScannerRejectionReason =
  typeof PASSPORT_SCANNER_REJECTION_REASONS[number];
export type PublicFlowReason = typeof PUBLIC_FLOW_REASONS[number];

export type PublicFlowTelemetryPayload =
  | {
      event: "visa_photo_rejection";
      reason: VisaPhotoRejectionReason;
    }
  | {
      event: "passport_scanner_rejection";
      reason: PassportScannerRejectionReason;
    }
  | {
      event: "public_flow";
      reason: PublicFlowReason;
    };

export interface StableReasonState<Reason extends string> {
  candidate: Reason | null;
  candidateSinceMs: number | null;
  emitted: readonly Reason[];
}

export function createStableReasonState<
  Reason extends string,
>(): StableReasonState<Reason> {
  return {
    candidate: null,
    candidateSinceMs: null,
    emitted: [],
  };
}

export function advanceStableReason<Reason extends string>(
  state: StableReasonState<Reason>,
  reason: Reason | null,
  nowMs: number,
  stableWindowMs = 1_000,
): {
  state: StableReasonState<Reason>;
  emittedReason: Reason | null;
} {
  if (!reason) {
    return {
      state: {
        ...state,
        candidate: null,
        candidateSinceMs: null,
      },
      emittedReason: null,
    };
  }
  if (state.emitted.includes(reason)) {
    return {
      state: {
        ...state,
        candidate: reason,
        candidateSinceMs: state.candidate === reason
          ? state.candidateSinceMs
          : nowMs,
      },
      emittedReason: null,
    };
  }
  if (state.candidate !== reason || state.candidateSinceMs === null) {
    return {
      state: {
        ...state,
        candidate: reason,
        candidateSinceMs: nowMs,
      },
      emittedReason: null,
    };
  }
  if (nowMs - state.candidateSinceMs < stableWindowMs) {
    return { state, emittedReason: null };
  }
  return {
    state: {
      candidate: reason,
      candidateSinceMs: state.candidateSinceMs,
      emitted: [...state.emitted, reason],
    },
    emittedReason: reason,
  };
}

export function visaPhotoRejectionReason(input: {
  cameraUnavailable: boolean;
  qualityModelUnavailable: boolean;
  faceStatus:
    | "loading"
    | "no_face"
    | "multiple"
    | "too_far"
    | "too_close"
    | "off_center"
    | "head_tilt"
    | "ready"
    | "unavailable";
  backgroundStatus: "checking" | "white" | "not_white" | "not_plain";
  clarityStatus: "checking" | "good" | "too_dark" | "too_bright" | "blurry";
  eyewearStatus: "checking" | "clear" | "detected" | "uncertain";
}): VisaPhotoRejectionReason | null {
  if (input.cameraUnavailable) return "camera_unavailable";
  if (
    input.qualityModelUnavailable
    || input.faceStatus === "unavailable"
  ) {
    return "quality_model_unavailable";
  }
  const faceReasons: Partial<
    Record<typeof input.faceStatus, VisaPhotoRejectionReason>
  > = {
    no_face: "no_face",
    multiple: "multiple_faces",
    too_far: "too_far",
    too_close: "too_close",
    off_center: "off_center",
    head_tilt: "head_tilt",
  };
  const faceReason = faceReasons[input.faceStatus];
  if (faceReason) return faceReason;
  if (input.faceStatus !== "ready") return null;

  if (input.eyewearStatus === "detected") return "eyewear_detected";
  if (input.eyewearStatus === "uncertain") return "eyewear_uncertain";
  if (input.eyewearStatus !== "clear") return null;
  if (input.clarityStatus === "too_dark") return "too_dark";
  if (input.clarityStatus === "too_bright") return "too_bright";
  if (input.clarityStatus === "blurry") return "blurry";
  if (input.clarityStatus !== "good") return null;
  if (input.backgroundStatus === "not_white") {
    return "background_not_light_neutral";
  }
  if (input.backgroundStatus === "not_plain") {
    return "background_not_plain";
  }
  return null;
}

export function passportScannerRejectionReason(input: {
  failureReason:
    | "camera_unavailable"
    | "crop_validation_failed"
    | null;
  frameStatus:
    | "checking"
    | "no_document"
    | "incomplete_document"
    | "too_small"
    | "sideways"
    | "upside_down"
    | "excessive_skew"
    | "multiple_documents"
    | "screen_or_book"
    | "missing_mrz"
    | "not_passport_page"
    | "ready";
  passportDetected: boolean;
  glareStatus: "checking" | "clear" | "glare";
  lightingStatus: "checking" | "good" | "too_dark" | "too_bright";
  blurStatus: "checking" | "sharp" | "blurry";
}): PassportScannerRejectionReason | null {
  if (input.failureReason) return input.failureReason;
  if (!input.passportDetected) {
    return input.frameStatus === "checking" || input.frameStatus === "ready"
      ? null
      : input.frameStatus;
  }
  if (input.glareStatus === "checking") return null;
  if (input.glareStatus === "glare") return "glare";
  if (input.lightingStatus === "checking") return null;
  if (input.lightingStatus === "too_dark") return "too_dark";
  if (input.lightingStatus === "too_bright") return "too_bright";
  if (input.blurStatus === "checking" || input.blurStatus === "sharp") {
    return null;
  }
  return "blurry";
}

export function isPublicFlowTelemetryPayload(
  value: unknown,
): value is PublicFlowTelemetryPayload {
  if (!value || typeof value !== "object") return false;
  const keys = Object.keys(value);
  if (
    keys.length !== 2
    || !keys.includes("event")
    || !keys.includes("reason")
  ) {
    return false;
  }
  const candidate = value as { event?: unknown; reason?: unknown };
  if (
    typeof candidate.event !== "string"
    || typeof candidate.reason !== "string"
  ) {
    return false;
  }
  if (candidate.event === "visa_photo_rejection") {
    return (VISA_PHOTO_REJECTION_REASONS as readonly string[])
      .includes(candidate.reason);
  }
  if (candidate.event === "passport_scanner_rejection") {
    return (PASSPORT_SCANNER_REJECTION_REASONS as readonly string[])
      .includes(candidate.reason);
  }
  if (candidate.event === "public_flow") {
    return (PUBLIC_FLOW_REASONS as readonly string[])
      .includes(candidate.reason);
  }
  return false;
}

export function parseTelemetryQueue(
  raw: string | null,
  maximumSize = 32,
): PublicFlowTelemetryPayload[] {
  if (!raw || raw.length > 8_192) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isPublicFlowTelemetryPayload)
      .slice(-maximumSize);
  } catch {
    return [];
  }
}

export function enqueueTelemetry(
  queue: readonly PublicFlowTelemetryPayload[],
  payload: PublicFlowTelemetryPayload,
  maximumSize = 32,
): PublicFlowTelemetryPayload[] {
  return [...queue, payload].slice(-maximumSize);
}
