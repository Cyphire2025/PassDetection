"use client";

import { Mic, Square, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { LiquidSculptureHero } from "@/components/ui/liquid-sculpture-hero";
import { useVoiceInput } from "../hooks/use-voice-input";
import styles from "./voice-preview.module.css";

export function VoicePreview() {
  const { status, error, levelRef, start, stop } = useVoiceInput();
  const controlRef = useRef<HTMLDivElement>(null);
  const listening = status === "listening";
  const requesting = status === "requesting";
  const active = listening || requesting;

  useEffect(() => {
    if (!listening) return;
    const control = controlRef.current;
    let frame = 0;
    const paint = () => {
      control?.style.setProperty("--voice-level", String(levelRef.current));
      frame = requestAnimationFrame(paint);
    };
    paint();
    return () => {
      cancelAnimationFrame(frame);
      control?.style.setProperty("--voice-level", "0");
    };
  }, [listening, levelRef]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") stop(); };
    if (active) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, stop]);

  const label = listening ? "Stop microphone" : requesting ? "Cancel microphone request" : "Start microphone";
  const Icon = listening ? Square : requesting ? X : Mic;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand} aria-label="Global Connects">
          <span className={styles.monogram} aria-hidden="true">gc<span>↗</span></span>
          <span>Global Connects</span>
        </div>
        <span className={styles.previewBadge}><span /> Voice preview</span>
      </header>

      <section className={styles.experience} aria-labelledby="voice-heading">
        <div className={styles.introduction}>
          <p className={styles.eyebrow}>A little closer. A little more human.</p>
          <h1 id="voice-heading">A voice, <em>taking shape.</em></h1>
        </div>

        <div className={styles.sculpture}>
          <LiquidSculptureHero levelRef={levelRef} />
        </div>

        <div className={styles.controls} ref={controlRef} data-listening={listening}>
          <div className={styles.microphoneWrap}>
            <span className={styles.voiceRing} aria-hidden="true" />
            <button type="button" className={styles.microphone} onClick={() => active ? stop() : void start()} aria-label={label} aria-pressed={active} aria-describedby="voice-status voice-privacy">
              <Icon size={23} strokeWidth={1.6} aria-hidden="true" fill={listening ? "currentColor" : "none"} />
            </button>
          </div>
          <div className={styles.status} id="voice-status" role="status" aria-live="polite" aria-atomic="true">
            <p>{listening ? "Listening to you" : requesting ? "Allow your microphone" : "Let’s hear you"}</p>
            <span>{listening ? "Speak, and watch it take shape. Tap to stop." : requesting ? "Approve access in your browser. Tap to cancel." : "Tap the microphone, then say something."}</span>
          </div>
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
        </div>
      </section>

      <footer className={styles.footer}>
        <span id="voice-privacy">Just your voice & the moment. Audio stays on your device.</span>
        <span className={styles.signature}>Made to <em>connect.</em></span>
      </footer>
    </main>
  );
}
