"use client";

import Image from "next/image";
import { useEffect, useRef, type RefObject } from "react";
import { LiquidEngine } from "./liquid-sculpture/engine";
import type { EngineOptions, SculpturePresentation } from "./liquid-sculpture/types";
import styles from "./liquid-sculpture/sculpture.module.css";

const SCULPTURE = "/ai/liquid-sculpture.webp";

function engineOptions(reducedMotion: boolean): EngineOptions {
  return {
    interactive: false, strength: 1.1, radius: 280, density: 0.85,
    dotSize: 1, spread: 0.85, turbulence: 0.9, returnSpeed: 1.2,
    streaks: true, restStyle: "image", ambient: true, ambientIntensity: 0.65,
    speed: 0.48, intro: false, reducedMotion, bg: [235 / 255, 233 / 255, 229 / 255],
    imgBg: null, liquid: 0.85,
  };
}

/** Voice-driven adaptation of Sculpture Hero by guglielmogiannattasio.it / 21st.dev. */
export function LiquidSculptureHero({ levelRef, presentationRef }: { levelRef: RefObject<number>; presentationRef?: RefObject<SculpturePresentation> }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

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
    const fail = () => { root.dataset.renderer = "image"; };

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
          }
        } catch { fail(); }
      };
      next.onerror = fail;
      next.src = SCULPTURE;
    };

    try {
      engine = new LiquidEngine(canvas, engineOptions(motion.matches), fail);
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
    motion.addEventListener("change", onMotion);
    document.addEventListener("visibilitychange", visible);
    load();
    return () => {
      disposed = true;
      observer.disconnect();
      intersection.disconnect();
      motion.removeEventListener("change", onMotion);
      document.removeEventListener("visibilitychange", visible);
      engine?.destroy();
      canvas.remove();
    };
  }, [levelRef, presentationRef]);

  return (
    <div className={styles.root} ref={rootRef} data-testid="voice-sculpture">
      <div className={styles.fallback}>
        <Image src={SCULPTURE} alt="An interwoven horizontal sculpture of silver and sand-colored filaments" fill priority sizes="(max-width: 639px) 100vw, 1200px" unoptimized />
      </div>
      <div ref={stageRef} className={styles.stage} />
    </div>
  );
}
