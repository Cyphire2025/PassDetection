"use client";

import Image from "next/image";
import { useEffect, useImperativeHandle, useRef, type Ref, type RefObject } from "react";
import { LiquidEngine } from "./liquid-sculpture/engine";
import { paintSculptureMatte } from "./liquid-sculpture/matte";
import type { EngineOptions, SculptureHandle, SculpturePresentation } from "./liquid-sculpture/types";
import styles from "./liquid-sculpture/sculpture.module.css";

const SCULPTURE = "/ai/liquid-sculpture.webp";

function engineOptions(reducedMotion: boolean): EngineOptions {
  return {
    interactive: true, strength: 1.1, radius: 280, density: 1.05,
    dotSize: 1, spread: 0.85, turbulence: 0.9, returnSpeed: 1.2,
    streaks: true, restStyle: "image", ambient: true, ambientIntensity: 1.25,
    speed: 0.9, intro: false, reducedMotion, bg: [235 / 255, 233 / 255, 229 / 255],
    imgBg: null, liquid: 0.85,
  };
}

/** Voice-driven adaptation of Sculpture Hero by guglielmogiannattasio.it / 21st.dev. */
export function LiquidSculptureHero({ levelRef, presentationRef, dark = false, ref }: { levelRef: RefObject<number>; presentationRef?: RefObject<SculpturePresentation>; dark?: boolean; ref?: Ref<SculptureHandle> }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const matteRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<LiquidEngine | null>(null);
  useImperativeHandle(ref, () => ({ invalidate: () => engineRef.current?.renderPresentation() }), []);

  useEffect(() => {
    const root = rootRef.current;
    const stage = stageRef.current;
    if (!root || !stage) return;
    const canvas = document.createElement("canvas");
    canvas.className = styles.canvas;
    canvas.setAttribute("aria-hidden", "true");
    stage.appendChild(canvas);
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let engine: LiquidEngine | null = null;
    let disposed = false;
    let image: HTMLImageElement | null = null;
    let imageRequest = 0;
    let intersecting = true;
    const fail = () => {
      root.dataset.renderer = "image";
      if (image && matteRef.current && root.dataset.matte !== "ready" && paintSculptureMatte(matteRef.current, image)) root.dataset.matte = "ready";
    };

    const resize = () => {
      const width = root.clientWidth;
      const height = root.clientHeight;
      const aspect = image ? image.naturalWidth / image.naturalHeight : 1983 / 793;
      const imageWidth = Math.min(width, height * aspect * 0.96);
      const imageHeight = imageWidth / aspect;
      engine?.resize(width, height, {
        x: (width - imageWidth) / 2, y: (height - imageHeight) / 2,
        w: imageWidth, h: imageHeight,
      });
    };

    const load = () => {
      const request = ++imageRequest;
      const next = new window.Image();
      next.decoding = "async";
      next.onload = () => {
        if (disposed || request !== imageRequest) return;
        image = next;
        try {
          resize();
          if (engine) {
            engine.onFirstFrame = () => {
              if (!disposed && request === imageRequest) root.dataset.renderer = "webgl";
            };
            engine.setImage(next);
          } else fail();
        } catch { fail(); }
      };
      next.onerror = fail;
      next.src = SCULPTURE;
    };

    try {
      engine = new LiquidEngine(canvas, engineOptions(motion.matches), fail);
      engineRef.current = engine;
      engine.readVoiceLevel = () => levelRef.current;
      engine.readPresentation = () => presentationRef?.current ?? null;
    } catch { fail(); }
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    const visible = () => engine?.setVisible(intersecting && !document.hidden);
    const intersection = new IntersectionObserver(([entry]) => {
      intersecting = entry.isIntersecting;
      visible();
    });
    intersection.observe(root);
    const onMotion = () => engine?.setOptions({ reducedMotion: motion.matches });
    // Listen on the shared stage so the image viewer can receive clicks while
    // the same particles behind its boundary still respond to pointer movement.
    const pointerSurface = root.parentElement ?? root;
    const pointer = (event: PointerEvent) => {
      const bounds = root.getBoundingClientRect();
      const type = event.type === "pointerleave" ? "leave" : event.type === "pointerdown" ? "down" : event.type === "pointerup" || event.type === "pointercancel" ? "up" : "move";
      engine?.pointer(type, event.clientX-bounds.left, event.clientY-bounds.top, event.pointerType !== "mouse");
    };
    const pointerEvents = ["pointermove", "pointerdown", "pointerup", "pointercancel", "pointerleave"] as const;
    for (const event of pointerEvents) pointerSurface.addEventListener(event, pointer, { passive: true });
    motion.addEventListener("change", onMotion);
    document.addEventListener("visibilitychange", visible);
    load();
    return () => {
      disposed = true;
      observer.disconnect();
      intersection.disconnect();
      motion.removeEventListener("change", onMotion);
      for (const event of pointerEvents) pointerSurface.removeEventListener(event, pointer);
      document.removeEventListener("visibilitychange", visible);
      engine?.destroy();
      engineRef.current = null;
      canvas.remove();
    };
  }, [levelRef, presentationRef]);
  useEffect(() => { engineRef.current?.setOptions({ dark }); }, [dark]);

  return (
    <div className={styles.root} ref={rootRef} data-testid="voice-sculpture" data-theme={dark ? "dark" : "light"}>
      <div className={styles.fallback}>
        <Image src={SCULPTURE} alt="An interwoven horizontal sculpture of silver and sand-colored filaments" fill priority sizes="(max-width: 639px) 100vw, 1200px" unoptimized />
        <canvas ref={matteRef} className={styles.matte} aria-hidden="true" />
      </div>
      <div ref={stageRef} className={styles.stage} />
    </div>
  );
}
