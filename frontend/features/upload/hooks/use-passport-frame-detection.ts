import { useEffect, useRef, useState, type RefObject } from "react";
import {
  type PassportFrameStatus,
} from "../services/passport-frame-detector";
import {
  detectRectangularPassportFrame,
  type RectangularPassportFrameResult,
} from "../services/passport-rectangular-frame-detector";
import {
  CAMERA_QUALITY_POLICY,
  isCameraMotionStable,
  updateRollingCameraReadiness,
} from "../services/camera-quality-policy";

const REQUIRED_STATUS_FRAMES = 2;

interface UsePassportFrameDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  guideRef?: RefObject<HTMLElement | null>;
  enabled: boolean;
  resetKey?: string | number;
}

interface StabilizedFrameAnalysis extends RectangularPassportFrameResult {
  resetKey: string | number;
  detectionSequence: number;
}

/** Keeps page analysis and multi-frame stability outside the camera UI. */
export function usePassportFrameDetection({
  videoRef,
  canvasRef,
  guideRef,
  enabled,
  resetKey = 0,
}: UsePassportFrameDetectionOptions) {
  const [analysis, setAnalysis] = useState<StabilizedFrameAnalysis | null>(null);
  const readinessSamplesRef = useRef<boolean[]>([]);
  const previousMotionSignatureRef = useRef<Uint8Array | null>(null);
  const readyRef = useRef(false);
  const readySequenceRef = useRef(0);
  const lastStatusRef = useRef<PassportFrameStatus | null>(null);
  const statusFramesRef = useRef(0);

  useEffect(() => {
    readinessSamplesRef.current = [];
    previousMotionSignatureRef.current = null;
    readyRef.current = false;
    readySequenceRef.current = 0;
    lastStatusRef.current = null;
    statusFramesRef.current = 0;
    if (!enabled) {
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;
      const result = detectRectangularPassportFrame(
        videoRef.current,
        canvasRef.current,
        guideRef?.current ?? null,
      );
      const motionStable = isCameraMotionStable(
        previousMotionSignatureRef.current,
        result.motionSignature,
      );
      previousMotionSignatureRef.current = result.motionSignature;
      const passing = result.isDetected
        && result.lightingStatus === "good"
        && motionStable;
      const readiness = updateRollingCameraReadiness(
        readinessSamplesRef.current,
        passing,
        readyRef.current,
      );
      const wasReady = readyRef.current;
      readinessSamplesRef.current = readiness.samples;
      readyRef.current = readiness.ready;
      if (readiness.ready && !wasReady) readySequenceRef.current += 1;

      if (lastStatusRef.current === result.status) {
        statusFramesRef.current = Math.min(
          REQUIRED_STATUS_FRAMES,
          statusFramesRef.current + 1,
        );
      } else {
        lastStatusRef.current = result.status;
        statusFramesRef.current = 1;
      }
      const stableFailureStatus = statusFramesRef.current
        >= REQUIRED_STATUS_FRAMES
        ? result.status
        : "checking";
      setAnalysis({
        ...result,
        isDetected: readiness.ready,
        status: readiness.ready
          ? "ready"
          : passing || result.isDetected
            ? "checking"
            : stableFailureStatus,
        resetKey,
        detectionSequence: readySequenceRef.current,
      });
    }, CAMERA_QUALITY_POLICY.liveAnalysisIntervalMs);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, guideRef, resetKey, videoRef]);

  const isCurrentAnalysis = enabled && analysis?.resetKey === resetKey;
  const hasStableDetection = isCurrentAnalysis && Boolean(analysis?.isDetected);
  const status = isCurrentAnalysis
    ? analysis?.status ?? "checking"
    : "checking";
  return {
    isDetected: hasStableDetection,
    status,
    confidence: enabled ? analysis?.confidence ?? 0 : 0,
    visibleEdges: enabled ? analysis?.visibleEdges ?? 0 : 0,
    lightingStatus: isCurrentAnalysis
      ? analysis?.lightingStatus ?? "good"
      : "good",
    meanLuminance: enabled ? analysis?.meanLuminance ?? 0 : 0,
    isCriticalZoneObstructed: false,
    hasDocumentCandidate: isCurrentAnalysis
      && (analysis?.visibleEdges ?? 0) >= 2,
    detectionSequence: isCurrentAnalysis
      ? analysis?.detectionSequence ?? 0
      : 0,
  };
}
