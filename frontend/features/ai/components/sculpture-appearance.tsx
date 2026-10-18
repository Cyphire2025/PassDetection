"use client";

import { Check, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { SculptureAppearance } from "@/components/ui/liquid-sculpture/types";
import styles from "./appearance.module.css";

const SHAPES = [{ value: "sculpture", label: "Sculpture", mark: "∿" }, { value: "logo", label: "Company logo", mark: "gc" }, { value: "text", label: "Text", mark: "Aa" }, { value: "emoji", label: "Emoji", mark: "☺" }, { value: "face", label: "Talking face", mark: "◉" }] as const;
const EMOJIS = [{ value: "smile", label: "Smile", mark: "☺" }, { value: "heart", label: "Heart", mark: "♥" }, { value: "plane", label: "Plane", mark: "✈" }, { value: "globe", label: "Globe", mark: "◎" }, { value: "star", label: "Star", mark: "★" }] as const;

export function SculptureAppearanceControl({ value, onChange, renderer }: { value: SculptureAppearance; onChange: (value: SculptureAppearance) => void; renderer: "webgl" | "image" | null }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(value.text);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); trigger.current?.focus(); } };
    root.current?.querySelector<HTMLElement>("[data-shape-choice]")?.focus();
    document.addEventListener("pointerdown", close); root.current?.addEventListener("keydown", key);
    const element = root.current;
    return () => { document.removeEventListener("pointerdown", close); element?.removeEventListener("keydown", key); };
  }, [open]);
  return <div className={styles.root} ref={root}>
    <button ref={trigger} type="button" className={styles.trigger} onClick={() => setOpen(!open)} aria-label="Sculpture appearance" aria-expanded={open} aria-controls="sculpture-appearance-panel"><Sparkles size={18} /></button>
    {open ? <div className={styles.panel} id="sculpture-appearance-panel" role="dialog" aria-label="Sculpture appearance">
      <div className={styles.heading}><div><h2>Give it a shape</h2><p>The same particles, in a different form.</p></div><button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} aria-label="Close sculpture appearance"><X size={16} /></button></div>
      {renderer !== "webgl" ? <p className={styles.note} role="status">{renderer === "image" ? "Your device is showing the sculpture preview. Shape changes are unavailable here; voice and chat still work." : "Preparing your particle shapes…"}</p> : null}
      <fieldset disabled={renderer !== "webgl"} className={styles.controls}>
      <div className={styles.shapes} role="group" aria-label="Particle shape">{SHAPES.map((shape) => <button data-shape-choice key={shape.value} type="button" aria-pressed={value.mode === shape.value} onClick={() => onChange({ ...value, mode: shape.value })}><span aria-hidden="true">{shape.mark}</span>{shape.label}{value.mode === shape.value ? <Check size={12} /> : null}</button>)}</div>
      {value.mode === "text" ? <form className={styles.text} onSubmit={(event) => { event.preventDefault(); if (text.trim()) onChange({ ...value, text: text.trim() }); }}><label htmlFor="sculpture-morph-text">Your words</label><div><input id="sculpture-morph-text" value={text} onChange={(event) => setText(event.target.value)} maxLength={24} placeholder="Up to 24 characters" /><button type="submit" disabled={!text.trim()}>Form text</button></div></form> : null}
      {value.mode === "emoji" ? <div className={styles.emojis} role="group" aria-label="Particle emoji">{EMOJIS.map((emoji) => <button key={emoji.value} type="button" aria-label={emoji.label} aria-pressed={value.emoji === emoji.value} onClick={() => onChange({ ...value, emoji: emoji.value })}>{emoji.mark}</button>)}</div> : null}
      {value.mode === "face" ? <p className={styles.note}>A stylized face that speaks with the reply and settles into a soft idle expression.</p> : null}
      <label className={styles.motion}><input type="checkbox" checked={value.stateAnimations} onChange={(event) => onChange({ ...value, stateAnimations: event.target.checked })} /><span>Listening ripples, thinking folds &amp; speech waves</span></label>
      </fieldset>
      <p className={styles.note}>Mouse and voice interaction stay active. Choose Sculpture to flow back. Motion follows your device’s reduced-motion preference.</p>
    </div> : null}
  </div>;
}
