"use client";

import { Check, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { SculptureAppearance } from "@/components/ui/liquid-sculpture/types";
import styles from "./appearance.module.css";

const SHAPES = [{ value: "sculpture", label: "Sculpture", mark: "∿" }, { value: "face", label: "Human hologram", mark: "◉" }, { value: "test", label: "Test", mark: "◇" }] as const;

export function SculptureAppearanceControl({ value, onChange }: { value: SculptureAppearance; onChange: (value: SculptureAppearance) => void; renderer: "webgl" | "image" | null }) {
  const [open, setOpen] = useState(false);
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
      <div className={styles.heading}><div><h2>Give it a shape</h2><p>Choose the visual for your conversation.</p></div><button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} aria-label="Close sculpture appearance"><X size={16} /></button></div>
      <fieldset className={styles.controls}>
      <div className={styles.shapes} role="group" aria-label="Particle shape">{SHAPES.map((shape) => <button data-shape-choice key={shape.value} type="button" aria-pressed={value.mode === shape.value} onClick={() => onChange({ ...value, mode: shape.value })}><span aria-hidden="true">{shape.mark}</span>{shape.label}{value.mode === shape.value ? <Check size={12} /> : null}</button>)}</div>
      {value.mode === "face" ? <p className={styles.note}>A human particle hologram. Its appearance follows your selected voice in AI settings.</p> : null}
      {value.mode === "test" ? <p className={styles.note}>Explore a 3D particle face. Drag to rotate, move to illuminate. Its face follows your selected voice.</p> : null}
      <label className={styles.motion}><input type="checkbox" checked={value.stateAnimations} onChange={(event) => onChange({ ...value, stateAnimations: event.target.checked })} /><span>Animate with voice and pointer</span></label>
      </fieldset>
      <p className={styles.note}>Motion follows your device’s reduced-motion preference. A still view remains available when animation is unavailable.</p>
    </div> : null}
  </div>;
}
