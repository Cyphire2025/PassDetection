import type { PassportPageSide } from "../services/passport-camera-guide";
import type { PassportScannerRejectionReason } from "../services/public-flow-telemetry";

export interface SmartCameraProps {
  onCapture: (file: File) => void;
  onCancel: () => void;
  pageSide: PassportPageSide;
  allowFileFallback?: boolean;
  onTelemetryReason?: (reason: PassportScannerRejectionReason) => void;
}

