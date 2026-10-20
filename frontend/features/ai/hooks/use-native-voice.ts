"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { NativePlayback, pcmBase64 } from "../native-audio";
import { startNativeCapture } from "../native-capture";
import type { NativeEvent } from "../types";

type Session = { socket: WebSocket; playback: NativePlayback; capture?: () => void; frame: number; ready: boolean; paused?: boolean; saved?: boolean; finished?: (saved: boolean) => void };

export function useNativeVoice(onEvent: (event: NativeEvent) => void, onStopped: () => void) {
  const [active, setActive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState("");
  const [inputDetected, setInputDetected] = useState(false);
  const [inputHint, setInputHint] = useState("");
  const context = useRef<AudioContext | null>(null);
  const session = useRef<Session | null>(null);
  const playbackLevel = useRef(0);
  const callbacks = useRef({ onEvent, onStopped });
  useEffect(() => { callbacks.current = { onEvent, onStopped }; }, [onEvent, onStopped]);

  const teardown = useCallback((notify: boolean) => {
    const current = session.current; session.current = null;
    if (current) {
      current.finished?.(false);
      cancelAnimationFrame(current.frame); current.capture?.(); current.playback.dispose();
      current.socket.onmessage = current.socket.onopen = current.socket.onclose = current.socket.onerror = null;
      if (current.socket.readyState < WebSocket.CLOSING) current.socket.close(1000, "Voice session ended");
    }
    playbackLevel.current = 0;
    setActive(false); setConnecting(false); setSpeaking(false); setThinking(false); setRecovering(false); setEnding(false);
    setInputDetected(false); setInputHint("");
    if (notify && current) callbacks.current.onStopped();
  }, []);
  const stop = useCallback(() => teardown(true), [teardown]);
  const finish = useCallback(async (): Promise<boolean> => {
    const current = session.current;
    if (!current) return true;
    if (!current.ready || current.socket.readyState !== WebSocket.OPEN || current.finished) return false;
    setEnding(true); current.paused = true; current.capture?.(); current.capture = undefined; current.playback.clear();
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => { setError("The voice turn could not finish saving. Your typed draft is still here; try again."); teardown(true); }, 7000);
      current.finished = (saved) => { clearTimeout(timer); resolve(saved); };
      try { current.socket.send(JSON.stringify({ type: "end" })); }
      catch { teardown(true); }
    });
  }, [teardown]);
  const warm = useCallback(() => {
    try {
      if (!context.current || context.current.state === "closed") context.current = new AudioContext();
      void context.current.resume().catch(() => undefined); // Readiness validates this before capture begins.
    }
    catch { setError("Voice playback is unavailable in this browser. You can still type."); }
  }, []);

  const start = useCallback((stream: MediaStream, conversationId: string, attachmentIds: string[] = []) => {
    teardown(false); setError(""); warm();
    const audio = context.current;
    if (!audio) { setError("Voice audio is unavailable in this browser. You can still type."); callbacks.current.onStopped(); return; }
    setConnecting(true);
    let socket: WebSocket;
    try { socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v1/ai-assistant/voice`); }
    catch { setConnecting(false); setError("Voice could not connect. You can continue by typing."); callbacks.current.onStopped(); return; }
    const playback = new NativePlayback(audio, (value) => { if (session.current?.socket === socket) setSpeaking(value); });
    const current: Session = { socket, playback, frame: 0, ready: false }; session.current = current;
    const fail = (message: string) => { if (session.current !== current) return; setError(message); teardown(true); };
    const capture = startNativeCapture(audio, stream, {
      accepting: () => session.current === current && !current.paused,
      send: (buffer) => {
        if (socket.readyState !== WebSocket.OPEN) throw new Error("The voice connection ended. Tap the microphone to reconnect.");
        if (socket.bufferedAmount > 128 * 1024) throw new Error("The microphone connection is falling behind. Please reconnect.");
        socket.send(JSON.stringify({ type: "audio", data: pcmBase64(buffer) }));
      },
      onReady: () => { if (session.current === current) { setActive(true); setConnecting(false); } },
      onError: fail,
      onInput: (detected, hint) => { if (session.current === current) { setInputDetected(detected); setInputHint(hint); } },
    });
    current.capture = capture.stop;
    const samples = new Float32Array(playback.analyser.fftSize);
    const measure = () => {
      if (session.current !== current) return;
      playback.analyser.getFloatTimeDomainData(samples);
      let energy = 0; for (const value of samples) energy += value * value;
      const target = Math.min(1, Math.sqrt(energy / samples.length) * 6);
      playbackLevel.current += (target - playbackLevel.current) * .3;
      current.frame = requestAnimationFrame(measure);
    };
    const timer = setTimeout(() => fail("The voice connection took too long. Please try again."), 25000);
    socket.onopen = () => socket.send(JSON.stringify({ type: "start", session_id: crypto.randomUUID(), conversation_id: conversationId, attachment_ids: attachmentIds }));
    socket.onerror = () => { clearTimeout(timer); fail("Voice could not connect. Check the selected voice provider in AI settings, or continue by typing."); };
    socket.onclose = (event) => {
      clearTimeout(timer);
      if (session.current !== current) return;
      if (current.finished) {
        const saved = event.code === 1000 && current.saved === true;
        if (!saved) setError("The voice turn could not finish saving. Your typed draft is still here; try again.");
        current.finished(saved); current.finished = undefined;
      }
      if (event.code !== 1000) setError("The voice connection ended. Tap the microphone to reconnect.");
      teardown(true);
    };
    socket.onmessage = async ({ data }) => {
      if (session.current !== current) return;
      try {
        if (typeof data !== "string" || data.length > 512 * 1024) throw new Error("The voice message is invalid.");
        const event = JSON.parse(data) as NativeEvent;
        if (!event || typeof event.type !== "string") throw new Error("The voice message is invalid.");
        if (event.type === "ready") {
          if (current.ready) return;
          current.ready = true; clearTimeout(timer);
          capture.connect(); measure();
        } else if (event.type === "voice_saved") {
          if (event.conversation_id !== conversationId) throw new Error("The voice save confirmation was invalid.");
          current.saved = true;
        } else if (event.type === "heartbeat") {
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "heartbeat_ack" }));
        } else if (event.type === "audio") {
          if (typeof event.data !== "string" || event.sample_rate !== 24000) throw new Error("The voice audio format is invalid.");
          setThinking(false); playback.push(event.data, event.sample_rate);
        } else if (event.type === "interrupted") {
          playback.clear(); setThinking(false); callbacks.current.onEvent(event);
        } else if (event.type === "answer_reset") {
          current.paused = true; playback.clear(); setThinking(true); setRecovering(true); callbacks.current.onEvent(event);
        } else if (event.type === "error") {
          fail(typeof event.message === "string" ? event.message : "The voice session could not continue.");
        } else if (event.type === "status") {
          setThinking(event.phase === "thinking");
        } else {
          if (event.type === "input_transcript" || event.type === "text_delta") {
            if (typeof event.text !== "string" || event.text.length > 32000) throw new Error("The voice caption is invalid.");
          }
          if (event.type === "turn_complete") { current.paused = false; setThinking(false); setRecovering(false); }
          callbacks.current.onEvent(event);
        }
      } catch (cause) { fail(cause instanceof Error ? cause.message : "The voice connection was interrupted."); }
    };
    socket.addEventListener("close", () => clearTimeout(timer), { once: true });
  }, [teardown, warm]);

  const sendText = useCallback((text: string) => {
    const current = session.current;
    if (!current?.ready || current.paused || current.socket.readyState !== WebSocket.OPEN || !text.trim()) return false;
    current.playback.clear(); setThinking(true);
    current.socket.send(JSON.stringify({ type: "text", text: text.trim() })); return true;
  }, []);
  const clearError = useCallback(() => setError(""), []);
  useEffect(() => {
    const hidden = () => { if (document.hidden) stop(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && session.current) { event.preventDefault(); stop(); } };
    document.addEventListener("visibilitychange", hidden); window.addEventListener("pagehide", stop); window.addEventListener("keydown", escape);
    return () => { document.removeEventListener("visibilitychange", hidden); window.removeEventListener("pagehide", stop); window.removeEventListener("keydown", escape); teardown(false); void context.current?.close().catch(() => undefined); context.current = null; };
  }, [stop, teardown]);
  return { active, connecting, speaking, thinking, recovering, ending, error, inputDetected, inputHint, playbackLevel, warm, start, stop, finish, sendText, clearError };
}
