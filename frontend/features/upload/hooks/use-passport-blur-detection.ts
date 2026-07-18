import { useEffect, useRef, useState, type RefObject } from "react";
import { detectPassportBlur } from "../services/passport-blur-detector";

const ANALYSIS_INTERVAL_MS = 350;
const REQUIRED_STABLE_FRAMES = 2;

type BlurStatus = "checking" | "sharp" | "blurry";

interface UsePassportBlurDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  guideRef?: RefObject<HTMLElement | null>;
  enabled: boolean;
  resetKey?: string | number;
}

/** Samples focus quality and stabilizes the result across consecutive frames. */
export function usePassportBlurDetection({
  videoRef,
  canvasRef,
  guideRef,
  enabled,
  resetKey = 0,
}: UsePassportBlurDetectionOptions) {
  const [status, setStatus] = useState<BlurStatus>("checking");
  const [score, setScore] = useState(0);
  const [sampleResetKey, setSampleResetKey] = useState<string | number | null>(
    null,
  );
  const sharpFramesRef = useRef(0);

  useEffect(() => {
    sharpFramesRef.current = 0;
    if (!enabled) {
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;
      const result = detectPassportBlur(
        videoRef.current,
        canvasRef.current,
        guideRef?.current ?? null,
      );
      setSampleResetKey(resetKey);
      setScore(result.score);
      sharpFramesRef.current = result.isSharp
        ? Math.min(REQUIRED_STABLE_FRAMES, sharpFramesRef.current + 1)
        : 0;
      setStatus(sharpFramesRef.current >= REQUIRED_STABLE_FRAMES ? "sharp" : "blurry");
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, guideRef, resetKey, videoRef]);

  const currentStatus = enabled && sampleResetKey === resetKey
    ? status
    : "checking";
  return {
    status: currentStatus,
    score: enabled ? score : 0,
    isSharp: currentStatus === "sharp",
  };
}
