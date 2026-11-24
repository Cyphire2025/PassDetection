"use client";

import { useContext, useLayoutEffect, useState } from "react";
import { GroupBannerFrameContext } from "./group-banner-frame";

function cssPixels(value: string) {
  return Number.parseFloat(value) || 0;
}

function bannerImageBounds(target: Element) {
  const bounds = target.getBoundingClientRect();
  const style = getComputedStyle(target);
  return {
    width: bounds.width - cssPixels(style.borderLeftWidth) - cssPixels(style.borderRightWidth),
    height: bounds.height - cssPixels(style.borderTopWidth) - cssPixels(style.borderBottomWidth),
  };
}

export function useGroupImageAspect(kind: "banner" | "background") {
  const frame = useContext(GroupBannerFrameContext);
  const element = frame?.element;
  const previewing = frame?.previewing;
  const setPreviewing = frame?.setPreviewing;
  const [aspect, setAspect] = useState(kind === "banner" ? 4 : 1.6);

  useLayoutEffect(() => {
    if (kind !== "banner" || !setPreviewing) return;
    setPreviewing(true);
    return () => setPreviewing(false);
  }, [kind, setPreviewing]);

  useLayoutEffect(() => {
    // The first-image layout must commit before its content-sized frame is read.
    if (kind === "banner" && !previewing) return;
    const main = (element?.current ?? document.querySelector(".group-workspace"))?.closest("main");
    const target = kind === "banner" ? element?.current : main?.parentElement ?? main;
    if (!target) return;
    let active = true;
    const measure = () => {
      if (!active) return;
      const { width, height } = kind === "banner" ? bannerImageBounds(target) : target.getBoundingClientRect();
      if (width > 0 && height > 0) {
        const next = width / height;
        setAspect(current => current === next ? current : next);
      }
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(target);
    if (!observer) window.addEventListener("resize", measure);
    return () => {
      active = false;
      observer?.disconnect();
      if (!observer) window.removeEventListener("resize", measure);
    };
  }, [kind, element, previewing]);

  return aspect;
}
