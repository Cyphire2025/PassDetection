"use client";

import Image from "next/image";
import { gsap } from "gsap";
import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState, type RefObject } from "react";
import type { SculptureHandle, SculpturePresentation } from "@/components/ui/liquid-sculpture/types";
import type { SpeechFrame } from "../speech-frame";
import { loadHumanHead, type HumanHeadGeometry } from "./human-head-geometry";
import { TestHologramEngine, type HeadView } from "./test-hologram-engine";
import { HologramTransitions } from "./test-hologram-transitions";
import { LANDSCAPE_ORBIT_PITCH_MAX, LANDSCAPE_ORBIT_PITCH_MIN } from "./test-landscape-layout";
import styles from "./test-hologram.module.css";

type Props = { appearance: "male" | "female"; dark: boolean; motion: boolean; levelRef: RefObject<number>; presentationRef: RefObject<SculpturePresentation>; speechFrameRef: RefObject<SpeechFrame> };
type Control = "face" | "landscape";
const initialView = (): HeadView => ({ yaw: -.38, pitch: -.07, zoom: 1, landscapeYaw: 0, landscapePitch: 0, x: 0, y: 0, influence: 0, barrier: 0 });
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

export const TestHologram = forwardRef<SculptureHandle, Props>(function TestHologram({ appearance, dark, motion, levelRef, presentationRef, speechFrameRef }, ref) {
  const root = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef({ dark, motion });
  const wakeRef = useRef<() => void>(() => undefined);
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
    let keyboardHoldUntil = 0;
    let returningHome = false;
    let drag: { id: number; x: number; y: number; control: Control } | null = null;
    const touches = new Map<number, { x: number; y: number }>();
    let width = container.clientWidth, height = container.clientHeight;
    const resizeScene = () => {
      const bounds = container.getBoundingClientRect();
      width = bounds.width; height = bounds.height;
      engine?.resize(window.innerWidth, window.innerHeight, bounds);
    };
    const view = initialView(), target = initialView();
    const transitions = new HologramTransitions(target);
    const stop = () => { gsap.ticker.remove(draw); transitions.suspend(); engine?.suspend(); running = false; lastTime = 0; };
    const draw = () => {
      if (disposed || !engine || !ready || !visible || document.hidden) { stop(); return; }
      const now = performance.now();
      const animate = current.current.motion && !reduced.matches;
      transitions.advance(now, animate);
      const elapsed = lastTime ? Math.min((now - lastTime) / 1000, .25) : 1 / 60;
      lastTime = now;
      if (animate) clock += elapsed;
      const ease = animate ? 1 - Math.exp(-elapsed * (drag ? 18 : 9)) : 1;
      view.yaw += (target.yaw - view.yaw) * ease; view.pitch += (target.pitch - view.pitch) * ease;
      view.zoom += (target.zoom - view.zoom) * ease;
      view.landscapeYaw += (target.landscapeYaw - view.landscapeYaw) * ease;
      view.landscapePitch += (target.landscapePitch - view.landscapePitch) * ease;
      const atmosphereEase = animate ? 1 - Math.exp(-elapsed * 2.4) : 1;
      view.atmosphereX = (view.atmosphereX ?? 0) + ((target.atmosphereX ?? 0) - (view.atmosphereX ?? 0)) * atmosphereEase;
      view.atmosphereY = (view.atmosphereY ?? 0) + ((target.atmosphereY ?? 0) - (view.atmosphereY ?? 0)) * atmosphereEase;
      view.x += (target.x - view.x) * ease; view.y += (target.y - view.y) * ease;
      view.influence += (target.influence - view.influence) * (1 - Math.exp(-elapsed * 6));
      const interacting = animate && (target.influence > 0 || drag?.control === "face");
      view.barrier += ((interacting ? 1 : 0) - view.barrier) * (1 - Math.exp(-elapsed * (interacting ? 5 : 2.5)));
      const reveal = presentationRef.current.reveal;
      view.manipulating = drag?.control === "face" || now < keyboardHoldUntil || returningHome;
      if (returningHome && !transitions.resetting && Math.abs(view.yaw - target.yaw) + Math.abs(view.pitch - target.pitch)
        + Math.abs(view.zoom - target.zoom) + Math.abs(view.landscapeYaw - target.landscapeYaw) + Math.abs(view.landscapePitch - target.landscapePitch) < .001) returningHome = false;
      try { engine.draw(clock, view, speechFrameRef.current, current.current.dark, animate, (1 - reveal * .94) * transitions.opacity, levelRef.current); }
      catch { fail(); return; }
      if (!animate) stop();
    };
    const wake = () => { if (!running && !disposed && ready && visible && !document.hidden) { running = true; transitions.resume(performance.now()); gsap.ticker.add(draw); } };
    wakeRef.current = wake;
    const reset = () => {
      const initial = initialView();
      returningHome = true;
      transitions.cancelReset();
      view.yaw += engine?.resetRotation() ?? 0;
      // Return along the shortest arc, including after multiple complete turns.
      const nearest = (angle: number, home: number) => angle + Math.atan2(Math.sin(home - angle), Math.cos(home - angle));
      target.landscapeYaw = view.landscapeYaw; target.landscapePitch = view.landscapePitch;
      target.yaw = view.yaw; target.pitch = view.pitch; target.zoom = view.zoom;
      const destination = { landscapeYaw: nearest(target.landscapeYaw, 0), landscapePitch: 0,
        yaw: nearest(target.yaw, initial.yaw), pitch: initial.pitch, zoom: initial.zoom };
      if (current.current.motion && !reduced.matches) transitions.reset(destination, performance.now());
      else Object.assign(target, destination);
      wake();
    };
    const fail = () => { ready = false; stop(); engine?.destroy(true); engine = null; if (!disposed) setRendered({ appearance, state: "fallback" }); };
    const initialize = () => {
      if (disposed || !head) return;
      try {
        ready = false; engine?.destroy();
        const candidate = new TestHologramEngine(element, head, appearance); engine = candidate;
        resizeScene();
        void candidate.prepare().then(() => {
          if (disposed || engine !== candidate) return;
          ready = true;
          if (current.current.motion && !reduced.matches) transitions.enter();
          else transitions.advance(performance.now(), false);
          setRendered({ appearance, state: "webgl" }); wake();
        }).catch(() => { if (!disposed && engine === candidate) fail(); });
      }
      catch { fail(); }
    };
    void loadHumanHead(appearance, abort.signal).then((value) => { if (!disposed) { head = value; initialize(); } }).catch(() => { if (!disposed) fail(); });
    const move = (event: PointerEvent) => {
      if (event.pointerType === "touch" && !touches.has(event.pointerId)) return;
      if (touches.has(event.pointerId)) touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
      let pointerX = event.clientX, pointerY = event.clientY;
      if (touches.size > 1) {
        pointerX = 0; pointerY = 0;
        touches.forEach((point) => { pointerX += point.x / touches.size; pointerY += point.y / touches.size; });
      }
      const rect = element.getBoundingClientRect();
      target.x = (event.clientX - rect.left) / Math.max(1, rect.width) * 2 - 1;
      target.y = 1 - (event.clientY - rect.top) / Math.max(1, rect.height) * 2;
      const activeControl = drag?.control ?? (event.shiftKey ? "landscape" : "face");
      target.influence = activeControl === "face" ? 1 : 0;
      if (drag && (drag.id === event.pointerId || touches.size > 1)) {
        const yaw = (pointerX - drag.x) / Math.max(200, width) * Math.PI * 2;
        const pitch = (pointerY - drag.y) / Math.max(200, height);
        if (activeControl === "landscape") {
          target.landscapeYaw += yaw;
          target.landscapePitch = clamp(target.landscapePitch + pitch * .6, LANDSCAPE_ORBIT_PITCH_MIN, LANDSCAPE_ORBIT_PITCH_MAX);
        } else {
          target.yaw += yaw;
          target.pitch = clamp(target.pitch + pitch * 2, -.65, .65);
        }
        drag.x = pointerX; drag.y = pointerY;
      }
      // Keep the hover active until the pointer leaves. A slow render must not
      // expire an input event before the user gets to see its response.
      wake();
    };
    const down = (event: PointerEvent) => {
      if (!ready || event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
      if (event.pointerType === "touch") {
        touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (drag) {
          container.setPointerCapture(event.pointerId);
          drag.control = "landscape"; drag.x = 0; drag.y = 0;
          touches.forEach((point) => { drag!.x += point.x / touches.size; drag!.y += point.y / touches.size; });
          target.influence = 0; wake(); return;
        }
      }
      if (drag) return;
      returningHome = false;
      transitions.cancelReset();
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, control: event.shiftKey ? "landscape" : "face" }; container.setPointerCapture(event.pointerId); element.focus({ preventScroll: true }); move(event);
    };
    const up = (event: PointerEvent) => { if (drag?.id !== event.pointerId && !touches.has(event.pointerId)) return; release(); };
    const leave = () => { if (!drag) { target.influence = 0; wake(); } };
    const release = () => {
      const pointer = drag?.id; drag = null;
      const capturedTouches = [...touches.keys()]; touches.clear();
      capturedTouches.forEach((id) => { if (container.hasPointerCapture(id)) container.releasePointerCapture(id); });
      if (pointer !== undefined && container.hasPointerCapture(pointer)) container.releasePointerCapture(pointer);
      target.influence = 0; target.atmosphereX = 0; target.atmosphereY = 0; wake();
    };
    // The atmosphere responds across the viewport, including outside the portrait.
    // Touch remains an explicit drag; it must not leave a persistent hover offset.
    const atmosphereMove = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      target.atmosphereX = clamp(event.clientX / Math.max(1, window.innerWidth) * 2 - 1, -1, 1);
      target.atmosphereY = clamp(1 - event.clientY / Math.max(1, window.innerHeight) * 2, -1, 1);
      wake();
    };
    const atmosphereLeave = (event: PointerEvent) => { if (!event.relatedTarget) { target.atmosphereX = 0; target.atmosphereY = 0; wake(); } };
    const key = (event: KeyboardEvent) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "+", "-", "="].includes(event.key)) return;
      event.preventDefault();
      transitions.cancelReset();
      if (event.key !== "Home") {
        returningHome = false;
        if (!(event.shiftKey && event.key.startsWith("Arrow"))) keyboardHoldUntil = performance.now() + 300;
      }
      if (event.key === "Home") reset();
      else if (event.shiftKey && event.key.startsWith("Arrow")) {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") target.landscapeYaw += event.key === "ArrowLeft" ? Math.PI / 12 : -Math.PI / 12;
        if (event.key === "ArrowUp" || event.key === "ArrowDown") target.landscapePitch = clamp(target.landscapePitch + (event.key === "ArrowUp" ? .04 : -.04), LANDSCAPE_ORBIT_PITCH_MIN, LANDSCAPE_ORBIT_PITCH_MAX);
      }
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
    container.addEventListener("pointermove", move); container.addEventListener("pointerdown", down); container.addEventListener("pointerup", up); container.addEventListener("pointercancel", up); container.addEventListener("lostpointercapture", release); container.addEventListener("pointerleave", leave); container.addEventListener("dblclick", reset); element.addEventListener("keydown", key);
    element.addEventListener("webglcontextlost", lost); element.addEventListener("webglcontextrestored", initialize);
    window.addEventListener("resize", onResize);
    window.addEventListener("blur", release);
    window.addEventListener("pointermove", atmosphereMove, { passive: true });
    window.addEventListener("pointerout", atmosphereLeave, { passive: true });
    document.addEventListener("visibilitychange", visibility); reduced.addEventListener("change", wake);
    return () => {
      disposed = true; abort.abort(); stop(); transitions.cancelReset(); resize.disconnect(); intersection.disconnect();
      // Fast Refresh and Strict Mode restart this effect on the same canvas.
      // Lose the context only after that canvas is actually retired from the DOM.
      engine?.destroy(!element.isConnected); head = null;
      container.removeEventListener("pointermove", move); container.removeEventListener("pointerdown", down); container.removeEventListener("pointerup", up); container.removeEventListener("pointercancel", up); container.removeEventListener("lostpointercapture", release); container.removeEventListener("pointerleave", leave); container.removeEventListener("dblclick", reset); element.removeEventListener("keydown", key);
      window.removeEventListener("resize", onResize);
      element.removeEventListener("webglcontextlost", lost); element.removeEventListener("webglcontextrestored", initialize); document.removeEventListener("visibilitychange", visibility); reduced.removeEventListener("change", wake);
      window.removeEventListener("blur", release);
      window.removeEventListener("pointermove", atmosphereMove); window.removeEventListener("pointerout", atmosphereLeave);
      wakeRef.current = () => undefined;
    };
  }, [appearance, levelRef, presentationRef, speechFrameRef]);
  return <div ref={root} className={styles.root} aria-busy={renderer === "loading"} data-testid="particle-face-test" data-renderer={renderer} data-appearance={appearance} data-motion={motion} data-theme={dark ? "dark" : "light"}>
    {renderer !== "webgl" ? <div className={styles.fallback}><Image src={`/ai/human-head/${appearance}-still.png`} fill unoptimized alt={`${appearance === "male" ? "Male" : "Female"} 3D hologram still view`} sizes="(max-width: 639px) 80vw, 480px" /></div> : null}
    <canvas key={appearance} ref={canvas} className={styles.canvas} tabIndex={renderer === "webgl" ? 0 : -1} aria-hidden={renderer !== "webgl"} role="img" aria-label={`${appearance === "male" ? "Male" : "Female"} interactive 3D particle face`} aria-describedby={instructions} />
    <span id={instructions} className={styles.screenReader}>Move to stir the snow. The face rotates at rest and pauses while you or the assistant speaks. Drag to rotate the face. Shift-drag, two-finger drag, or Shift with arrow keys explores the 360 degree landscape. Arrow keys rotate the face; plus and minus zoom. Home or double-click restores the original view.</span>
  </div>;
});
