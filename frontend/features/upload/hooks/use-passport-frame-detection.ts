import { useEffect, useRef, useState, type RefObject } from "react";
import {
  type PassportFrameStatus,
  type PassportPageSide,
} from "../services/passport-frame-detector";
import {
  detectRectangularPassportFrame,
  type RectangularPassportFrameResult,
} from "../services/passport-rectangular-frame-detector";

const ANALYSIS_INTERVAL_MS = 180;
// Two agreeing edge-only frames (~0.36 seconds) keep the guide responsive
// without turning a single transient boundary into a capture-ready state.
const REQUIRED_STABLE_FRAMES = 2;
const REQUIRED_STATUS_FRAMES = 2;

interface UsePassportFrameDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  guideRef?: RefObject<HTMLElement | null>;
  enabled: boolean;
  pageSide?: PassportPageSide;
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
  pageSide = "front",
  resetKey = 0,
}: UsePassportFrameDetectionOptions) {
  const [analysis, setAnalysis] = useState<StabilizedFrameAnalysis | null>(null);
  const readyFramesRef = useRef(0);
  const readySequenceRef = useRef(0);
  const lastStatusRef = useRef<PassportFrameStatus | null>(null);
  const statusFramesRef = useRef(0);

  useEffect(() => {
    readyFramesRef.current = 0;
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
      const reliablyDetected = result.isDetected;

      if (reliablyDetected) {
        const wasStable = readyFramesRef.current >= REQUIRED_STABLE_FRAMES;
        readyFramesRef.current = Math.min(
          REQUIRED_STABLE_FRAMES,
          readyFramesRef.current + 1,
        );
        lastStatusRef.current = "ready";
        statusFramesRef.current = readyFramesRef.current;
        const stable = readyFramesRef.current >= REQUIRED_STABLE_FRAMES;
        if (stable && !wasStable) readySequenceRef.current += 1;
        setAnalysis({
          ...result,
          isDetected: stable,
          status: stable ? "ready" : "checking",
          resetKey,
          detectionSequence: readySequenceRef.current,
        });
        return;
      }

      readyFramesRef.current = 0;
      if (lastStatusRef.current === result.status) {
        statusFramesRef.current = Math.min(
          REQUIRED_STATUS_FRAMES,
          statusFramesRef.current + 1,
        );
      } else {
        lastStatusRef.current = result.status;
        statusFramesRef.current = 1;
      }
      setAnalysis({
        ...result,
        isDetected: false,
        status: statusFramesRef.current >= REQUIRED_STATUS_FRAMES
          ? result.status
          : "checking",
        resetKey,
        detectionSequence: readySequenceRef.current,
      });
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, guideRef, pageSide, resetKey, videoRef]);

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
    isCriticalZoneObstructed: false,
    hasDocumentCandidate: isCurrentAnalysis
      && (analysis?.visibleEdges ?? 0) >= 2,
    detectionSequence: isCurrentAnalysis
      ? analysis?.detectionSequence ?? 0
      : 0,
  };
}
