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
  guideRef?: RefObject<HTMLElement | null>;
  enabled: boolean;
  resetKey?: string | number;
}

/** Stabilizes exposure guidance before the camera UI reacts to it. */
export function usePassportLightingDetection({
  videoRef,
  canvasRef,
  guideRef,
  enabled,
  resetKey = 0,
}: UsePassportLightingDetectionOptions) {
  const [status, setStatus] = useState<LightingStatus | "checking">("checking");
  const [meanLuminance, setMeanLuminance] = useState(0);
  const [darkPixelRatio, setDarkPixelRatio] = useState(0);
  const [brightPixelRatio, setBrightPixelRatio] = useState(0);
  const [sampleResetKey, setSampleResetKey] = useState<
    string | number | null
  >(null);
  const lastRawStatusRef = useRef<LightingStatus | null>(null);
  const stableFramesRef = useRef(0);

  useEffect(() => {
    lastRawStatusRef.current = null;
    stableFramesRef.current = 0;
    if (!enabled) {
      return;
    }

    const interval = window.setInterval(() => {
      if (!videoRef.current || !canvasRef.current) return;

      const result = detectPassportLighting(
        videoRef.current,
        canvasRef.current,
        guideRef?.current ?? null,
      );
      setSampleResetKey(resetKey);
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
      } else {
        setStatus("checking");
      }
    }, ANALYSIS_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [canvasRef, enabled, guideRef, resetKey, videoRef]);

  const currentStatus = enabled && sampleResetKey === resetKey
    ? status
    : "checking";
  return {
    status: currentStatus,
    isWellLit: currentStatus === "good",
    meanLuminance: enabled ? meanLuminance : 0,
    darkPixelRatio: enabled ? darkPixelRatio : 0,
    brightPixelRatio: enabled ? brightPixelRatio : 0,
  };
}
