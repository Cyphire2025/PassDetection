import { type VisaCameraProfile } from "./visa-camera.types";

export const ANALYSIS_TIMEOUT_MS = 6_000;

export const CAMERA_STOP_DRAIN_TIMEOUT_MS = 1_500;

export const ANALYSIS_WIDTH = 96;

export const ANALYSIS_HEIGHT = 144;

export const LIVE_FACE_DETECTION_CONFIDENCE = 0.55;

export const VISA_CAPTURE_MARGIN_RATIO = 0.02;

/** The earlier relaxed checks stay wired behind this switch for an explicit rollback. */
export const ACTIVE_VISA_CAMERA_PROFILE: VisaCameraProfile = "strict";
