"use client";

import { useEffect } from "react";

const TRIGGER = 'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex]:not([tabindex="-1"])';
let pointerTrigger: HTMLElement | null = null;

/** Safari does not necessarily focus a button when the pointer activates it. */
export function ModalFocusTracker() {
  useEffect(() => {
    const remember = (event: PointerEvent) => {
      const candidate = event.target instanceof Element ? event.target.closest(TRIGGER) : null;
      pointerTrigger = candidate instanceof HTMLElement ? candidate : null;
    };
    const clear = () => { pointerTrigger = null; };
    document.addEventListener("pointerdown", remember, true);
    document.addEventListener("keydown", clear, true);
    return () => {
      document.removeEventListener("pointerdown", remember, true);
      document.removeEventListener("keydown", clear, true);
      clear();
    };
  }, []);
  return null;
}

export function modalReturnTarget(dialog: HTMLElement): HTMLElement | null {
  const pointer = pointerTrigger;
  pointerTrigger = null;
  if (pointer?.isConnected && !dialog.contains(pointer)) return pointer;
  return document.activeElement instanceof HTMLElement ? document.activeElement : null;
}
