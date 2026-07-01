import { useEffect, useRef, useState, type RefObject } from "react";
import { detectPassportFrame } from "../services/passport-frame-detector";

const ANALYSIS_INTERVAL_MS = 400;
const REQUIRED_STABLE_FRAMES = 3;

interface UsePassportFrameDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  enabled: boolean;
}

/** Keeps frame analysis and stability rules outside the camera UI. */
export function usePassportFrameDetection({
  videoRef,
  canvasRef,
  enabled,
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
      const result = detectPassportFrame(videoRef.current, canvasRef.current);
      stableFramesRef.current = result.isDetected
        ? Math.min(REQUIRED_STABLE_FRAMES, stableFramesRef.current + 1)
        : Math.max(0, stableFramesRef.current - 1);
      setIsDetected(stableFramesRef.current >= REQUIRED_STABLE_FRAMES);
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, videoRef]);

  return { isDetected: enabled && isDetected };
}
