"use client";

import { useEffect, useRef } from "react";
import styles from "./launcher.module.css";

/** A small, continuously flowing torus of the sculpture's sand and silver filaments. */
export function AssistantOrb({ animated = true }: { animated?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext("2d");
    if (!element || !context) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    element.width = element.height = 64 * dpr;
    context.scale(dpr, dpr);
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let last = -100;
    const draw = (now: number) => {
      const moving = animated && !reduced.matches;
      const t = moving ? now / 6000 : 0;
      if (now - last > 32 || !moving) {
        last = now;
        context.clearRect(0, 0, 64, 64);
        for (let layer = 0; layer < 34; layer++) {
          const seed = layer * 2.39996;
          const gradient = context.createLinearGradient(10, 10, 54, 54);
          gradient.addColorStop(0, `rgba(205,188,158,${.25 + layer % 4 * .08})`);
          gradient.addColorStop(.45, `rgba(94,94,88,${.28 + layer % 3 * .08})`);
          gradient.addColorStop(.72, `rgba(232,221,199,${.45 + layer % 3 * .1})`);
          gradient.addColorStop(1, "rgba(140,117,83,.6)");
          context.beginPath();
          for (let point = 0; point <= 96; point++) {
            const angle = point / 96 * Math.PI * 2;
            const radius = 18 + Math.sin(seed) * 3.4 + Math.sin(angle * 3 + seed + t) * 2.3 + Math.sin(angle * 2 - t * 1.2 + seed) * 1.4;
            const x = 32 + Math.cos(angle) * radius;
            const y = 32 + Math.sin(angle) * radius;
            if (!point) context.moveTo(x, y); else context.lineTo(x, y);
          }
          context.closePath(); context.strokeStyle = gradient;
          context.lineWidth = .45 + layer % 4 * .2; context.stroke();
        }
        for (let index = 0; index < 90; index++) {
          const angle = index * 2.39996 + t * .13;
          const radius = 17 + Math.sin(index * 7.1 + t) * 8;
          context.beginPath(); context.arc(32 + Math.cos(angle) * radius, 32 + Math.sin(angle) * radius, index % 11 === 0 ? .7 : .3, 0, Math.PI * 2);
          context.fillStyle = `rgba(121,105,80,${.18 + index % 4 * .1})`; context.fill();
        }
      }
      if (moving && !document.hidden) frame = requestAnimationFrame(draw);
    };
    const resume = () => { cancelAnimationFrame(frame); draw(performance.now()); };
    reduced.addEventListener("change", resume);
    document.addEventListener("visibilitychange", resume);
    draw(performance.now());
    return () => { cancelAnimationFrame(frame); reduced.removeEventListener("change", resume); document.removeEventListener("visibilitychange", resume); };
  }, [animated]);
  return <span className={styles.orb} aria-hidden="true"><canvas ref={canvas} /></span>;
}
