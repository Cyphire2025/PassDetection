"use client";
import { useEffect, useRef, type ReactNode } from "react";
import styles from "./review-details-column.module.css";

/** Tall details scroll normally until their bottom is visible, then wait for the images. */
export function ReviewDetailsColumn({ children }: { children: ReactNode }) {
  const column = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = column.current;
    if (!element) return;
    const measure = () => {
      const top = Math.min(24, window.innerHeight - element.getBoundingClientRect().height - 24);
      element.style.setProperty("--review-sticky-top", `${Math.floor(top)}px`);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, []);
  return <div ref={column} className={`${styles.column} space-y-5`} data-review-details>{children}</div>;
}
