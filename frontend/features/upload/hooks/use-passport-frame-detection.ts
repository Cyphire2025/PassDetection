import { useEffect, useRef, useState, type RefObject } from "react";
import { detectPassportFrame, type PassportPageSide } from "../services/passport-frame-detector";

const ANALYSIS_INTERVAL_MS = 180;
// A document must remain fully inside the guide for ~0.72 seconds before the
// camera can advertise it as capture-ready. This avoids a false auto-click
// while a hand, table edge, or partially-visible document crosses the guide.
const REQUIRED_STABLE_FRAMES = 4;

interface UsePassportFrameDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  enabled: boolean;
  pageSide?: PassportPageSide;
}

/** Keeps frame analysis and stability rules outside the camera UI. */
export function usePassportFrameDetection({
  videoRef,
  canvasRef,
  enabled,
  pageSide = "front",
}: UsePassportFrameDetectionOptions) {
  const [isDetected, setIsDetected] = useState(false);
  const stableFramesRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      stableFramesRef.current = 0;
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;
      const result = detectPassportFrame(videoRef.current, canvasRef.current, pageSide);
      const reliablyDetected = result.isDetected && result.confidence >= 0.64;
      stableFramesRef.current = reliablyDetected
        ? Math.min(REQUIRED_STABLE_FRAMES, stableFramesRef.current + 1)
        : Math.max(0, stableFramesRef.current - 1);
      setIsDetected(stableFramesRef.current >= REQUIRED_STABLE_FRAMES);
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, pageSide, videoRef]);

  return { isDetected: enabled && isDetected };
}
