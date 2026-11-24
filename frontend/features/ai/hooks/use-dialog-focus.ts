import { useEffect, type RefObject } from "react";

export function useDialogFocus(open: boolean, root: RefObject<HTMLDivElement | null>, close: () => void) {
  useEffect(() => {
    if (!open || !root.current) return;
    const previous = document.activeElement as HTMLElement | null;
    const element = root.current;
    const focusable = () => [...element.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, [tabindex="0"]')];
    focusable()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close(); }
      if (event.key !== "Tab") return;
      const items = focusable(); const first = items[0]; const last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    element.addEventListener("keydown", key);
    return () => { element.removeEventListener("keydown", key); if (previous?.isConnected) previous.focus(); };
  }, [open, root, close]);
}
