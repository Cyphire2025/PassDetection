import { useEffect, useRef, useState, type RefObject } from "react";
import { detectPassportGlare } from "../services/passport-glare-detector";

const ANALYSIS_INTERVAL_MS = 350;
const REQUIRED_STABLE_FRAMES = 3;

type GlareStatus = "checking" | "clear" | "glare";

interface UsePassportGlareDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  guideRef?: RefObject<HTMLElement | null>;
  enabled: boolean;
  resetKey?: string | number;
}

/** Stabilizes localized glare detection before the UI reacts to it. */
export function usePassportGlareDetection({
  videoRef,
  canvasRef,
  guideRef,
  enabled,
  resetKey = 0,
}: UsePassportGlareDetectionOptions) {
  const [status, setStatus] = useState<GlareStatus>("checking");
  const [highlightRatio, setHighlightRatio] = useState(0);
  const [sampleResetKey, setSampleResetKey] = useState<string | number | null>(
    null,
  );
  const glareFramesRef = useRef(0);
  const clearFramesRef = useRef(0);

  useEffect(() => {
    glareFramesRef.current = 0;
    clearFramesRef.current = 0;
    if (!enabled) {
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;

      const result = detectPassportGlare(
        videoRef.current,
        canvasRef.current,
        guideRef?.current ?? null,
      );
      setSampleResetKey(resetKey);
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
      } else {
        setStatus("checking");
      }
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, guideRef, resetKey, videoRef]);

  const currentStatus: GlareStatus = enabled && sampleResetKey === resetKey
    ? status
    : "checking";
  return {
    status: currentStatus,
    hasGlare: currentStatus === "glare",
    highlightRatio: enabled ? highlightRatio : 0,
  };
}
