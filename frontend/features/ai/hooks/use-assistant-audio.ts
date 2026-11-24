"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { assistantApi, assistantMessage } from "../api";
import { speechChunks } from "../speech-text";
import { SpeechAnalyser } from "../speech-analyser";
import { neutralSpeechFrame } from "../speech-frame";
import { useVoiceInput } from "./use-voice-input";

type Playback = { source: AudioBufferSourceNode | null; analyser: AnalyserNode; speech: SpeechAnalyser; frame: number };

export function useAssistantAudio(onTranscript: (text: string) => void) {
  const microphone = useVoiceInput();
  const [speaking, setSpeaking] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");
  const playbackLevel = useRef(0);
  const speechFrame = useRef(neutralSpeechFrame());
  const context = useRef<AudioContext | null>(null);
  const playback = useRef<Playback | null>(null);
  const recording = useRef<MediaRecorder | null>(null);
  const speechRequest = useRef<AbortController | null>(null);
  const transcriptRequest = useRef<AbortController | null>(null);
  const recordingState = useRef<{ discarded: boolean } | null>(null);
  const continuousInput = useRef(false);
  const mounted = useRef(true);
  const transcript = useRef(onTranscript);
  const { stop: stopMicrophone, start: startMicrophone, getStream, clearError: clearMicrophoneError } = microphone;
  useEffect(() => { transcript.current = onTranscript; }, [onTranscript]);

  const stopPlayback = useCallback(() => {
    speechRequest.current?.abort(); speechRequest.current = null;
    const active = playback.current; playback.current = null; playbackLevel.current = 0;
    if (active) { cancelAnimationFrame(active.frame); active.source?.stop(); active.source?.disconnect(); active.analyser.disconnect(); active.speech.reset(); }
    if (mounted.current) { setSpeaking(false); setPreparing(false); }
  }, []);

  const warmAudio = useCallback(() => {
    try { context.current ??= new AudioContext(); void context.current.resume().catch(() => undefined); } catch { /* Text replies remain available. */ }
  }, []);

  const speak = useCallback(async (text: string) => {
    stopPlayback();
    setPreparing(true);
    const abort = new AbortController(); speechRequest.current = abort;
    try {
      const chunks = speechChunks(text);
      if (!chunks.length) { stopPlayback(); return; }
      warmAudio();
      const audioContext = context.current;
      if (!audioContext) throw new Error("Audio playback is unavailable in this browser.");
      const load = (index: number): Promise<AudioBuffer | Error> => assistantApi.speak(chunks[index], abort.signal)
        .then((blob) => blob.arrayBuffer()).then((bytes) => audioContext.decodeAudioData(bytes))
        .catch((cause) => new Error(assistantMessage(cause, "The spoken reply is unavailable. Your full text answer is still available.")));
      let queued = load(0);
      const analyser = audioContext.createAnalyser(); analyser.fftSize = 512;
      analyser.connect(audioContext.destination);
      const speech = new SpeechAnalyser(audioContext, analyser, speechFrame);
      const active: Playback = { source: null, analyser, speech, frame: 0 }; playback.current = active;
      const sample = () => {
        if (playback.current !== active) return;
        speech.sample(); playbackLevel.current = speechFrame.current.energy;
        active.frame = requestAnimationFrame(sample);
      };
      for (let index = 0; index < chunks.length; index++) {
        setPreparing(true);
        const buffer = await queued;
        if (abort.signal.aborted || !mounted.current) return;
        if (buffer instanceof Error) throw buffer;
        // Prefetch only one bounded chunk while the current one plays.
        if (index + 1 < chunks.length) queued = load(index + 1);
        const source = audioContext.createBufferSource(); source.buffer = buffer;
        source.connect(analyser); active.source = source;
        let releaseAbort = () => undefined as void;
        const finished = new Promise<void>((resolve, reject) => {
          const cancel = () => reject(new DOMException("Playback stopped", "AbortError"));
          releaseAbort = () => abort.signal.removeEventListener("abort", cancel);
          abort.signal.addEventListener("abort", cancel, { once: true });
          source.onended = () => resolve();
        });
        // The AudioContext is unlocked in the click gesture, including on iOS.
        void finished.catch(() => undefined);
        try {
          source.start(); setPreparing(false); setSpeaking(true);
          if (!active.frame) sample();
          await finished;
        } finally { releaseAbort(); source.disconnect(); if (active.source === source) active.source = null; }
      }
      if (!abort.signal.aborted) stopPlayback();
    } catch (cause) {
      if (!abort.signal.aborted && mounted.current) setError(assistantMessage(cause, "The spoken reply is unavailable. You can read the answer below."));
      if (!abort.signal.aborted) stopPlayback();
    }
  }, [stopPlayback, warmAudio]);

  const stopInput = useCallback((discard = false) => {
    if (recordingState.current && discard) recordingState.current.discarded = true;
    const recorder = recording.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    recording.current = null;
    stopMicrophone();
  }, [stopMicrophone]);

  const startInput = useCallback(async (connected: boolean, continuous = false) => {
    continuousInput.current = continuous;
    stopPlayback(); warmAudio(); setError("");
    await startMicrophone();
    const stream = getStream();
    if (!stream || !connected) return;
    if (typeof MediaRecorder === "undefined") { stopMicrophone(); setError("Voice messages are unavailable in this browser. You can type your question."); return; }
    try {
    const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 64000 } : undefined);
    const state = { discarded: false }; recordingState.current = state;
    recording.current = recorder;
    const chunks: Blob[] = []; let size = 0;
    recorder.ondataavailable = ({ data }) => { size += data.size; if (size <= 8 * 1024 * 1024) chunks.push(data); else stopInput(true); };
    recorder.onerror = () => { setError("The microphone recording was interrupted. Please try again."); stopInput(true); };
    recorder.onstop = () => {
      if (state.discarded || !mounted.current || !chunks.length) return;
      const abort = new AbortController(); transcriptRequest.current = abort;
      setTranscribing(true);
      void assistantApi.transcribe(new Blob(chunks, { type: recorder.mimeType }), abort.signal).then((text) => {
        if (!abort.signal.aborted && text.trim()) transcript.current(text);
      }).catch((cause) => { if (!abort.signal.aborted && mounted.current) setError(assistantMessage(cause, "Your voice message could not be transcribed.")); })
        .finally(() => { if (mounted.current) setTranscribing(false); });
    };
    recorder.start(250);
    } catch { stopInput(true); setError("Voice recording could not start. Check your microphone or type your question."); }
  }, [startMicrophone, getStream, stopMicrophone, stopInput, stopPlayback, warmAudio]);

  useEffect(() => {
    if (microphone.status !== "listening" || continuousInput.current) return;
    let frame = 0; const started = performance.now(); let lastSpeech = started; let heard = false;
    const inspect = () => {
      const now = performance.now();
      if (microphone.levelRef.current > .045) { lastSpeech = now; heard = true; }
      if (recording.current && ((heard && now - lastSpeech > 1400) || now - started > 60000)) { stopInput(!heard); return; }
      frame = requestAnimationFrame(inspect);
    };
    frame = requestAnimationFrame(inspect);
    return () => cancelAnimationFrame(frame);
  }, [microphone.status, microphone.levelRef, stopInput]);

  useEffect(() => {
    mounted.current = true;
    const hidden = () => { if (document.hidden) { stopInput(true); stopPlayback(); transcriptRequest.current?.abort(); } };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { stopInput(true); stopPlayback(); } };
    document.addEventListener("visibilitychange", hidden); window.addEventListener("keydown", escape);
    return () => { mounted.current = false; stopInput(true); stopPlayback(); transcriptRequest.current?.abort(); void context.current?.close().catch(() => undefined); context.current = null;
      document.removeEventListener("visibilitychange", hidden); window.removeEventListener("keydown", escape); };
  }, [stopInput, stopPlayback]);

  const clearError = useCallback(() => { setError(""); clearMicrophoneError(); }, [clearMicrophoneError]);
  return { microphone, speaking, preparing, transcribing, error: error || microphone.error, playbackLevel, speechFrame,
    startInput, stopInput, speak, stopPlayback, warmAudio, clearError };
}
