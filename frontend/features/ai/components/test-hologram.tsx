"use client";

import Image from "next/image";
import { RotateCcw } from "lucide-react";
import { gsap } from "gsap";
import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState, type RefObject } from "react";
import type { SculptureHandle, SculpturePresentation } from "@/components/ui/liquid-sculpture/types";
import type { SpeechFrame } from "../speech-frame";
import { loadHumanHead, type HumanHeadGeometry } from "./human-head-geometry";
import { TestHologramEngine, type HeadView } from "./test-hologram-engine";
import styles from "./test-hologram.module.css";

type Props = { appearance: "male" | "female"; dark: boolean; motion: boolean; levelRef: RefObject<number>; presentationRef: RefObject<SculpturePresentation>; speechFrameRef: RefObject<SpeechFrame> };
const initialView = (): HeadView => ({ yaw: -.18, pitch: .02, zoom: 1, x: 0, y: 0, influence: 0, barrier: 0 });
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

export const TestHologram = forwardRef<SculptureHandle, Props>(function TestHologram({ appearance, dark, motion, presentationRef, speechFrameRef }, ref) {
  const root = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef({ dark, motion });
  const wakeRef = useRef<() => void>(() => undefined), resetRef = useRef<() => void>(() => undefined);
  const [rendered, setRendered] = useState<{ appearance: string; state: "webgl" | "fallback" } | null>(null);
  const instructions = useId();
  const renderer = rendered?.appearance === appearance ? rendered.state : "loading";
  useImperativeHandle(ref, () => ({ invalidate: () => wakeRef.current() }), []);
  useEffect(() => { current.current = { dark, motion }; wakeRef.current(); }, [dark, motion]);
  useEffect(() => {
    const element = canvas.current, container = root.current;
    if (!element || !container) return;
    const abort = new AbortController(), reduced = matchMedia("(prefers-reduced-motion: reduce)");
    let engine: TestHologramEngine | null = null, head: HumanHeadGeometry | null = null;
    let running = false, ready = false, visible = true, disposed = false, lastTime = 0, clock = 0;
    let drag: { id: number; x: number; y: number } | null = null;
    let width = container.clientWidth, height = container.clientHeight;
    const resizeScene = () => {
      const bounds = container.getBoundingClientRect();
      width = bounds.width; height = bounds.height;
      engine?.resize(window.innerWidth, window.innerHeight, bounds);
    };
    const view = initialView(), target = initialView();
    const entrance = { opacity: 1 };
    const animations = gsap.context(() => {}, container);
    const stop = () => { gsap.ticker.remove(draw); running = false; lastTime = 0; };
    const draw = () => {
      if (disposed || !engine || !ready || !visible || document.hidden) { stop(); return; }
      const now = performance.now();
      const animate = current.current.motion && !reduced.matches;
      if (!animate) { gsap.killTweensOf(entrance); gsap.killTweensOf(target); entrance.opacity = 1; }
      const elapsed = lastTime ? Math.min((now - lastTime) / 1000, .25) : 1 / 60;
      lastTime = now;
      if (animate) clock += Math.min(elapsed, .05);
      const ease = animate ? 1 - Math.exp(-elapsed * (drag ? 18 : 9)) : 1;
      view.yaw += (target.yaw - view.yaw) * ease; view.pitch += (target.pitch - view.pitch) * ease;
      view.zoom += (target.zoom - view.zoom) * ease;
      view.x += (target.x - view.x) * ease; view.y += (target.y - view.y) * ease;
      view.influence += (target.influence - view.influence) * (1 - Math.exp(-elapsed * 6));
      const interacting = animate && (target.influence > 0 || drag !== null);
      view.barrier += ((interacting ? 1 : 0) - view.barrier) * (1 - Math.exp(-elapsed * (interacting ? 5 : 2.5)));
      const reveal = presentationRef.current.reveal;
      try { engine.draw(clock, view, speechFrameRef.current, current.current.dark, animate, (1 - reveal * .94) * entrance.opacity); }
      catch { fail(); return; }
      if (!animate) stop();
    };
    const wake = () => { if (!running && !disposed && ready && visible && !document.hidden) { running = true; gsap.ticker.add(draw); } };
    wakeRef.current = wake;
    const reset = () => {
      const initial = initialView();
      gsap.killTweensOf(target);
      if (current.current.motion && !reduced.matches) animations.add(() => { gsap.to(target, { yaw: initial.yaw, pitch: initial.pitch, zoom: initial.zoom, duration: .8, ease: "power3.out", onUpdate: wake }); });
      else { target.yaw = initial.yaw; target.pitch = initial.pitch; target.zoom = initial.zoom; }
      wake();
    };
    resetRef.current = reset;
    const fail = () => { ready = false; stop(); engine?.destroy(true); engine = null; if (!disposed) setRendered({ appearance, state: "fallback" }); };
    const initialize = () => {
      if (disposed || !head) return;
      try {
        ready = false; engine?.destroy();
        const candidate = new TestHologramEngine(element, head); engine = candidate;
        resizeScene();
        void candidate.prepare().then(() => {
          if (disposed || engine !== candidate) return;
          ready = true;
          if (current.current.motion && !reduced.matches) animations.add(() => { gsap.fromTo(entrance, { opacity: 0 }, { opacity: 1, duration: 1.2, ease: "power2.out" }); });
          else entrance.opacity = 1;
          setRendered({ appearance, state: "webgl" }); wake();
        }).catch(() => { if (!disposed && engine === candidate) fail(); });
      }
      catch { fail(); }
    };
    void loadHumanHead(appearance, abort.signal).then((value) => { if (!disposed) { head = value; initialize(); } }).catch(() => { if (!disposed) fail(); });
    const move = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect();
      target.x = (event.clientX - rect.left) / Math.max(1, rect.width) * 2 - 1;
      target.y = 1 - (event.clientY - rect.top) / Math.max(1, rect.height) * 2;
      target.influence = 1;
      if (drag?.id === event.pointerId) {
        target.yaw += (event.clientX - drag.x) / Math.max(200, width) * Math.PI * 2;
        target.pitch = clamp(target.pitch + (event.clientY - drag.y) / Math.max(200, height) * 2, -.65, .65);
        drag.x = event.clientX; drag.y = event.clientY;
      }
      // Keep the hover active until the pointer leaves. A slow render must not
      // expire an input event before the user gets to see its response.
      wake();
    };
    const down = (event: PointerEvent) => {
      if (event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
      gsap.killTweensOf(target);
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY }; container.setPointerCapture(event.pointerId); element.focus({ preventScroll: true }); move(event);
    };
    const up = (event: PointerEvent) => { if (drag?.id !== event.pointerId) return; drag = null; if (container.hasPointerCapture(event.pointerId)) container.releasePointerCapture(event.pointerId); target.influence = 0; wake(); };
    const leave = () => { if (!drag) { target.influence = 0; wake(); } };
    const release = () => { drag = null; target.influence = 0; wake(); };
    const key = (event: KeyboardEvent) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "+", "-", "="].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Home") reset();
      else if (event.key === "ArrowLeft" || event.key === "ArrowRight") target.yaw += event.key === "ArrowLeft" ? -.18 : .18;
      else if (event.key === "ArrowUp" || event.key === "ArrowDown") target.pitch = clamp(target.pitch + (event.key === "ArrowUp" ? -.1 : .1), -.65, .65);
      else target.zoom = clamp(target.zoom + (event.key === "-" ? -.08 : .08), .8, 1.18);
      wake();
    };
    const lost = (event: Event) => { event.preventDefault(); fail(); };
    const onResize = () => { resizeScene(); wake(); };
    const resize = new ResizeObserver(onResize); resize.observe(container);
    const intersection = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (!visible) stop(); else wake(); }); intersection.observe(container);
    const visibility = () => { if (document.hidden) stop(); else wake(); };
    container.addEventListener("pointermove", move); container.addEventListener("pointerdown", down); container.addEventListener("pointerup", up); container.addEventListener("pointercancel", up); container.addEventListener("lostpointercapture", release); container.addEventListener("pointerleave", leave); element.addEventListener("keydown", key);
    element.addEventListener("webglcontextlost", lost); element.addEventListener("webglcontextrestored", initialize);
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", visibility); reduced.addEventListener("change", wake);
    return () => {
      disposed = true; abort.abort(); stop(); animations.revert(); resize.disconnect(); intersection.disconnect(); engine?.destroy(true); head = null;
      container.removeEventListener("pointermove", move); container.removeEventListener("pointerdown", down); container.removeEventListener("pointerup", up); container.removeEventListener("pointercancel", up); container.removeEventListener("lostpointercapture", release); container.removeEventListener("pointerleave", leave); element.removeEventListener("keydown", key);
      window.removeEventListener("resize", onResize);
      element.removeEventListener("webglcontextlost", lost); element.removeEventListener("webglcontextrestored", initialize); document.removeEventListener("visibilitychange", visibility); reduced.removeEventListener("change", wake);
      wakeRef.current = resetRef.current = () => undefined;
    };
  }, [appearance, presentationRef, speechFrameRef]);
  return <div ref={root} className={styles.root} aria-busy={renderer === "loading"} data-testid="particle-face-test" data-renderer={renderer} data-appearance={appearance} data-motion={motion} data-theme={dark ? "dark" : "light"}>
    <div className={styles.stageGlow} aria-hidden="true" />
    {renderer !== "webgl" ? <div className={styles.fallback}><Image src={`/ai/human-head/${appearance}-still.png`} fill unoptimized alt={`${appearance === "male" ? "Male" : "Female"} 3D hologram still view`} sizes="(max-width: 639px) 80vw, 480px" /></div> : null}
    <canvas key={appearance} ref={canvas} className={styles.canvas} tabIndex={renderer === "webgl" ? 0 : -1} aria-hidden={renderer !== "webgl"} role="img" aria-label={`${appearance === "male" ? "Male" : "Female"} interactive 3D particle face`} aria-describedby={instructions} />
    <div className={styles.controls}><span id={instructions}>{renderer === "loading" ? "Preparing the 3D landscape…" : renderer === "fallback" ? "Still view · 3D graphics unavailable" : "Drag to rotate · Move to illuminate"}<span className={styles.screenReader}>. Use arrow keys to rotate, plus or minus to zoom, and Home to reset.</span></span><button type="button" aria-label="Reset 3D view" onClick={() => resetRef.current()} disabled={renderer !== "webgl"}><RotateCcw size={13} /></button></div>
    <span className={styles.signature} aria-hidden="true">TEST <span>/</span> HUMAN FORM</span>
  </div>;
});
