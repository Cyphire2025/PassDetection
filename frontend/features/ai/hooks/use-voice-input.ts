"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { requireRunningAudio } from "../audio-readiness";

type VoiceStatus = "idle" | "requesting" | "listening" | "error";
type Capture = {
  context: AudioContext;
  stream?: MediaStream;
  source?: MediaStreamAudioSourceNode;
  analyser?: AnalyserNode;
  frame: number;
};

function microphoneError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone access is blocked. Allow it in your browser, then try again.";
  }
  if (name === "NotFoundError") return "No microphone found. Connect one, then try again.";
  if (name === "NotReadableError") return "Your microphone is busy. Close other apps using it, then try again.";
  if (error instanceof Error && error.message.startsWith("Browser audio")) return error.message;
  return "The microphone couldn’t start. Please try again.";
}

/** Local volume analysis only: no recording, speech recognition, or network transport. */
export function useVoiceInput() {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const levelRef = useRef(0);
  const captureRef = useRef<Capture | null>(null);
  const requestRef = useRef(0);

  const release = useCallback(() => {
    requestRef.current += 1;
    const capture = captureRef.current;
    captureRef.current = null;
    levelRef.current = 0;
    if (!capture) return;
    cancelAnimationFrame(capture.frame);
    capture.stream?.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    capture.source?.disconnect();
    capture.analyser?.disconnect();
    void capture.context.close().catch(() => undefined);
  }, []);

  const stop = useCallback(() => {
    release();
    setStatus("idle");
    setError(null);
  }, [release]);

  const start = useCallback(async () => {
    if (captureRef.current) return;
    setError(null);
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
      setError("Open this page over HTTPS in a browser that supports microphone access.");
      setStatus("error");
      return;
    }

    const request = ++requestRef.current;
    setStatus("requesting");
    try {
      // Start within the click gesture, including on browsers that gate audio playback.
      const context = new AudioContext();
      const capture: Capture = { context, frame: 0 };
      captureRef.current = capture;
      const resume = context.resume();
      void resume.catch(() => undefined);
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: { ideal: 1 }, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      if (requestRef.current !== request) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      capture.stream = stream;
      await requireRunningAudio(context);
      if (requestRef.current !== request) return;

      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      const source = context.createMediaStreamSource(stream);
      source.connect(analyser);
      // Do not connect to the speakers: this is a visualizer, with no microphone echo.
      capture.source = source;
      capture.analyser = analyser;
      const samples = new Float32Array(analyser.fftSize);
      const sample = () => {
        if (captureRef.current !== capture) return;
        analyser.getFloatTimeDomainData(samples);
        let energy = 0;
        for (const value of samples) energy += value * value;
        const rms = Math.sqrt(energy / samples.length);
        const target = Math.min(1, Math.max(0, (rms - 0.008) * 8));
        levelRef.current += (target - levelRef.current) * (target > levelRef.current ? 0.4 : 0.1);
        capture.frame = requestAnimationFrame(sample);
      };
      stream.getAudioTracks().forEach((track) => {
        track.onended = () => {
          if (captureRef.current !== capture) return;
          release();
          setStatus("error");
          setError("The microphone disconnected. Reconnect it and try again.");
        };
      });
      setStatus("listening");
      sample();
    } catch (cause) {
      if (requestRef.current !== request) return;
      release();
      setStatus("error");
      setError(microphoneError(cause));
    }
  }, [release]);

  useEffect(() => {
    const onVisibility = () => { if (document.hidden) stop(); };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", stop);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", stop);
      release();
    };
  }, [release, stop]);

  const getStream = useCallback(() => captureRef.current?.stream, []);
  const clearError = useCallback(() => setError(""), []);
  return { status, error, levelRef, start, stop, getStream, clearError };
}
