import { useEffect, useRef, useState, type RefObject } from "react";
import {
  detectPassportLighting,
  type LightingStatus,
} from "../services/passport-lighting-detector";

const ANALYSIS_INTERVAL_MS = 350;
const REQUIRED_STABLE_FRAMES = 3;

interface UsePassportLightingDetectionOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  enabled: boolean;
}

/** Stabilizes exposure guidance before the camera UI reacts to it. */
export function usePassportLightingDetection({
  videoRef,
  canvasRef,
  enabled,
}: UsePassportLightingDetectionOptions) {
  const [status, setStatus] = useState<LightingStatus | "checking">("checking");
  const [meanLuminance, setMeanLuminance] = useState(0);
  const [darkPixelRatio, setDarkPixelRatio] = useState(0);
  const [brightPixelRatio, setBrightPixelRatio] = useState(0);
  const lastRawStatusRef = useRef<LightingStatus | null>(null);
  const stableFramesRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      lastRawStatusRef.current = null;
      stableFramesRef.current = 0;
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;

      const result = detectPassportLighting(videoRef.current, canvasRef.current);
      setMeanLuminance(result.meanLuminance);
      setDarkPixelRatio(result.darkPixelRatio);
      setBrightPixelRatio(result.brightPixelRatio);

      if (lastRawStatusRef.current === result.status) {
        stableFramesRef.current = Math.min(REQUIRED_STABLE_FRAMES, stableFramesRef.current + 1);
      } else {
        lastRawStatusRef.current = result.status;
        stableFramesRef.current = 1;
      }

      if (stableFramesRef.current >= REQUIRED_STABLE_FRAMES) {
        setStatus(result.status);
      }
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, videoRef]);

  return {
    status: enabled ? status : "checking",
    isWellLit: enabled && status === "good",
    meanLuminance: enabled ? meanLuminance : 0,
    darkPixelRatio: enabled ? darkPixelRatio : 0,
    brightPixelRatio: enabled ? brightPixelRatio : 0,
  };
}
