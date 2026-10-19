"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type RefObject } from "react";
import type { SculpturePresentation } from "@/components/ui/liquid-sculpture/types";
import { HologramEngine } from "./hologram-engine";
import styles from "./human-hologram.module.css";

export function HumanHologram({ appearance = "female", dark, motion = true, levelRef, presentationRef }: {
  appearance?: "male" | "female"; dark: boolean; motion?: boolean; levelRef: RefObject<number>; presentationRef: RefObject<SculpturePresentation>;
}) {
  const root = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const latest = useRef({ dark, motion });
  useEffect(() => { latest.current = { dark, motion }; }, [dark, motion]);
  const [rendered, setRendered] = useState<string | null>(null);
  const src = `/ai/hologram-${appearance}.png`;
  useEffect(() => {
    const element = canvas.current, container = root.current;
    if (!element || !container) return;
    let engine: HologramEngine | null = null, frame = 0, disposed = false, ready = false, visible = true, lastFrame = 0;
    const pointer = { x: 0, y: 0 }, target = { x: 0, y: 0 };
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const draw = (now: number) => {
      frame = 0;
      if (disposed || !ready || !visible || document.hidden) return;
      const animate = latest.current.motion && !reduced.matches;
      if (now - lastFrame > 32 || !animate) {
        lastFrame = now; pointer.x += (target.x - pointer.x) * .06; pointer.y += (target.y - pointer.y) * .06;
        engine?.draw(now / 1000, levelRef.current, presentationRef.current.phase === "speaking", latest.current.dark, animate, pointer);
      }
      if (animate) frame = requestAnimationFrame(draw);
    };
    const wake = () => { if (!frame && !disposed) frame = requestAnimationFrame(draw); };
    const fail = () => { ready = false; cancelAnimationFrame(frame); frame = 0; if (!disposed) setRendered(null); };
    const lost = (event: Event) => { event.preventDefault(); fail(); };
    const photo = new window.Image(); photo.decoding = "async";
    const initialize = () => { if (disposed) return; try { engine?.destroy(); engine = new HologramEngine(element); engine.setImage(photo); ready = true; engine.draw(0, 0, false, latest.current.dark, false, pointer); setRendered(src); wake(); } catch { engine?.destroy(); engine = null; fail(); } };
    photo.onload = initialize;
    photo.onerror = fail; photo.src = src;
    const move = (event: PointerEvent) => { const rect = container.getBoundingClientRect(); target.x = Math.max(-1, Math.min(1, (event.clientX - rect.left) / rect.width * 2 - 1)); target.y = Math.max(-1, Math.min(1, (event.clientY - rect.top) / rect.height * 2 - 1)); wake(); };
    const leave = () => { target.x = 0; target.y = 0; };
    const resize = new ResizeObserver(wake); resize.observe(container);
    const intersection = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; wake(); }); intersection.observe(container);
    const changes = new MutationObserver(wake); changes.observe(container, { attributes: true, attributeFilter: ["data-theme", "data-motion"] });
    container.addEventListener("pointermove", move, { passive: true }); container.addEventListener("pointerleave", leave);
    element.addEventListener("webglcontextlost", lost); element.addEventListener("webglcontextrestored", initialize); document.addEventListener("visibilitychange", wake); reduced.addEventListener("change", wake);
    return () => { disposed = true; cancelAnimationFrame(frame); photo.onload = null; photo.onerror = null; resize.disconnect(); intersection.disconnect(); changes.disconnect(); container.removeEventListener("pointermove", move); container.removeEventListener("pointerleave", leave); element.removeEventListener("webglcontextlost", lost); element.removeEventListener("webglcontextrestored", initialize); document.removeEventListener("visibilitychange", wake); reduced.removeEventListener("change", wake); engine?.destroy(); };
  }, [src, levelRef, presentationRef]);
  return <div ref={root} className={styles.root} data-testid="human-hologram" data-appearance={appearance} data-renderer={rendered === src ? "webgl" : "image"} data-theme={dark ? "dark" : "light"} data-motion={motion} role="img" aria-label={`${appearance === "male" ? "Male" : "Female"} human particle hologram`}>
    <div className={styles.fallback}><Image src={src} alt="" fill priority unoptimized sizes="(max-width: 639px) 75vw, 480px" /></div>
    <canvas ref={canvas} className={styles.canvas} aria-hidden="true" />
  </div>;
}
