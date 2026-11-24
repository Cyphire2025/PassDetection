"use client";

import { useRef, useState, useCallback } from "react";
import { useCameraCaptureLifecycle } from "./use-camera-capture-lifecycle";
import { SerializedVisaInferenceQueue, type VisaReadinessHysteresis, INITIAL_VISA_READINESS } from "../services/visa-selfie-runtime";
import {
  type PendingAnalysis,
  type PendingFinalAnalysis,
  type FaceStatus,
  type BackgroundStatus,
  type ClarityStatus,
} from "../components/visa-camera.types";
import { type VisaPhotoFaceGeometry, type VisaPhotoFinalValidation } from "../components/visa-selfie-quality";

export function useVisaCameraState() {
  const captureLifecycle = useCameraCaptureLifecycle();

  const videoRef = useRef<HTMLVideoElement>(null);

  const guideRef = useRef<HTMLDivElement>(null);

  const captureCanvasRef = useRef<HTMLCanvasElement>(null);

  const analysisCanvasRef = useRef<HTMLCanvasElement>(null);

  const streamRef = useRef<MediaStream | null>(null);

  const detectorRef = useRef<import("@mediapipe/face_detection").FaceDetection | null>(null);

  const detectorInferenceQueueRef =
    useRef(new SerializedVisaInferenceQueue());

  const animationFrameRef = useRef<number | null>(null);

  const lastAnalysisRef = useRef(0);

  const captureStartedRef = useRef(false);

  const captureReadyRef = useRef(false);

  const cameraGenerationRef = useRef(0);

  const detectorGenerationRef = useRef(0);

  const nextAnalysisIdRef = useRef(0);

  const activeAnalysisIdRef = useRef<number | null>(null);

  const pendingAnalysesRef = useRef(new Map<number, PendingAnalysis[]>());

  const pendingFinalAnalysisRef = useRef<PendingFinalAnalysis | null>(null);

  const faceStatusRef = useRef<FaceStatus>("loading");

  const previousFaceRef = useRef<VisaPhotoFaceGeometry | null>(null);

  const backgroundStatusRef = useRef<BackgroundStatus>("checking");

  const visaReadinessRef = useRef<VisaReadinessHysteresis>({
    ...INITIAL_VISA_READINESS,
  });

  const visibilityPausedRef = useRef(false);

  const [isCameraReady, setIsCameraReady] = useState(false);

  const [mirrorPreview, setMirrorPreview] = useState(false);

  const [cameraAttempt, setCameraAttempt] = useState(0);

  const [isDetectorReady, setIsDetectorReady] = useState(false);

  const [cameraError, setCameraError] = useState<string | null>(null);

  const [faceStatus, setFaceStatus] = useState<FaceStatus>("loading");

  const [backgroundStatus, setBackgroundStatus] = useState<BackgroundStatus>("checking");

  const [clarityStatus, setClarityStatus] = useState<ClarityStatus>("checking");

  const [liveReady, setLiveReady] = useState(false);

  const [fallbackAcknowledged, setFallbackAcknowledged] = useState(false);

  const [modelError, setModelError] = useState<string | null>(null);

  const [initializationAttempt, setInitializationAttempt] = useState(0);

  const [capturedFile, setCapturedFile] = useState<File | null>(null);

  const [capturedPreview, setCapturedPreview] = useState<string | null>(null);

  const [finalValidation, setFinalValidation] =
    useState<VisaPhotoFinalValidation | null>(null);

  const [borderlineConfirmed, setBorderlineConfirmed] = useState(false);

  const [isProcessing, setIsProcessing] = useState(false);

  const [processingError, setProcessingError] = useState<string | null>(null);

  const resetQualityState = useCallback((status: FaceStatus = "loading") => {
    faceStatusRef.current = status;
    previousFaceRef.current = null;
    backgroundStatusRef.current = "checking";
    captureReadyRef.current = false;
    visaReadinessRef.current = { ...INITIAL_VISA_READINESS };
    setFaceStatus(status);
    setBackgroundStatus("checking");
    setClarityStatus("checking");
    setLiveReady(false);
  }, []);
  return {
    captureLifecycle,
    videoRef,
    guideRef,
    captureCanvasRef,
    analysisCanvasRef,
    streamRef,
    detectorRef,
    detectorInferenceQueueRef,
    animationFrameRef,
    lastAnalysisRef,
    captureStartedRef,
    captureReadyRef,
    cameraGenerationRef,
    detectorGenerationRef,
    nextAnalysisIdRef,
    activeAnalysisIdRef,
    pendingAnalysesRef,
    pendingFinalAnalysisRef,
    faceStatusRef,
    previousFaceRef,
    backgroundStatusRef,
    visaReadinessRef,
    visibilityPausedRef,
    isCameraReady,
    setIsCameraReady,
    mirrorPreview,
    setMirrorPreview,
    cameraAttempt,
    setCameraAttempt,
    isDetectorReady,
    setIsDetectorReady,
    cameraError,
    setCameraError,
    faceStatus,
    setFaceStatus,
    backgroundStatus,
    setBackgroundStatus,
    clarityStatus,
    setClarityStatus,
    liveReady,
    setLiveReady,
    fallbackAcknowledged,
    setFallbackAcknowledged,
    modelError,
    setModelError,
    initializationAttempt,
    setInitializationAttempt,
    capturedFile,
    setCapturedFile,
    capturedPreview,
    setCapturedPreview,
    finalValidation,
    setFinalValidation,
    borderlineConfirmed,
    setBorderlineConfirmed,
    isProcessing,
    setIsProcessing,
    processingError,
    setProcessingError,
    resetQualityState,
  };
}

export type VisaCameraState = ReturnType<typeof useVisaCameraState>;
