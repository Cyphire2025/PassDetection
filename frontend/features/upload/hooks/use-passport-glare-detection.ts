import { useEffect, useRef, useState, type RefObject } from "react";
import { detectPassportGlare } from "../services/passport-glare-detector";

const ANALYSIS_INTERVAL_MS = 350;
const REQUIRED_STABLE_FRAMES = 3;

type GlareStatus = "checking" | "clear" | "glare";

interface UsePassportGlareDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  enabled: boolean;
}

/** Stabilizes localized glare detection before the UI reacts to it. */
export function usePassportGlareDetection({
  videoRef,
  canvasRef,
  enabled,
}: UsePassportGlareDetectionOptions) {
  const [status, setStatus] = useState<GlareStatus>("checking");
  const [highlightRatio, setHighlightRatio] = useState(0);
  const glareFramesRef = useRef(0);
  const clearFramesRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      glareFramesRef.current = 0;
      clearFramesRef.current = 0;
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;

      const result = detectPassportGlare(videoRef.current, canvasRef.current);
      setHighlightRatio(result.highlightRatio);

      if (result.hasGlare) {
        glareFramesRef.current = Math.min(REQUIRED_STABLE_FRAMES, glareFramesRef.current + 1);
        clearFramesRef.current = 0;
      } else {
        clearFramesRef.current = Math.min(REQUIRED_STABLE_FRAMES, clearFramesRef.current + 1);
        glareFramesRef.current = 0;
      }

      if (glareFramesRef.current >= REQUIRED_STABLE_FRAMES) {
        setStatus("glare");
      } else if (clearFramesRef.current >= REQUIRED_STABLE_FRAMES) {
        setStatus("clear");
      }
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, videoRef]);

  return {
    status: enabled ? status : "checking",
    hasGlare: enabled && status === "glare",
    highlightRatio: enabled ? highlightRatio : 0,
  };
}
