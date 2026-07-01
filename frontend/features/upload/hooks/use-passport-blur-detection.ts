import { useEffect, useRef, useState, type RefObject } from "react";
import { detectPassportBlur } from "../services/passport-blur-detector";

const ANALYSIS_INTERVAL_MS = 350;
const REQUIRED_STABLE_FRAMES = 2;

type BlurStatus = "checking" | "sharp" | "blurry";

interface UsePassportBlurDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  enabled: boolean;
}

/** Samples focus quality and stabilizes the result across consecutive frames. */
export function usePassportBlurDetection({ videoRef, canvasRef, enabled }: UsePassportBlurDetectionOptions) {
  const [status, setStatus] = useState<BlurStatus>("checking");
  const [score, setScore] = useState(0);
  const sharpFramesRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      sharpFramesRef.current = 0;
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;
      const result = detectPassportBlur(videoRef.current, canvasRef.current);
      setScore(result.score);
      sharpFramesRef.current = result.isSharp
        ? Math.min(REQUIRED_STABLE_FRAMES, sharpFramesRef.current + 1)
        : 0;
      setStatus(sharpFramesRef.current >= REQUIRED_STABLE_FRAMES ? "sharp" : "blurry");
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, videoRef]);

  return {
    status: enabled ? status : "checking",
    score: enabled ? score : 0,
    isSharp: enabled && status === "sharp",
  };
}
