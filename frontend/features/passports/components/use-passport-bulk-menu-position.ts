import { useLayoutEffect, useRef, useState, type RefObject } from "react";

interface Position {
  left: number;
  top: number;
  maxHeight: number;
}

export function usePassportBulkMenuPosition(
  isOpen: boolean,
  triggerRef: RefObject<HTMLButtonElement | null>,
  popupRef: RefObject<HTMLDivElement | null>,
) {
  const [position, setPosition] = useState<Position | null>(null);
  const focused = useRef(false);
  useLayoutEffect(() => {
    if (!isOpen) {
      focused.current = false;
      return;
    }
    const trigger = triggerRef.current;
    const popup = popupRef.current;
    if (!trigger || !popup) return;
    const update = () => {
      const margin = 8;
      const gap = 6;
      const anchor = trigger.getBoundingClientRect();
      const menu = popup.getBoundingClientRect();
      const maxHeight = Math.max(0, window.innerHeight - margin * 2);
      const height = Math.min(menu.height, maxHeight);
      const below = window.innerHeight - anchor.bottom - gap - margin;
      const top = below >= height ? anchor.bottom + gap : anchor.top - gap - height;
      const next = {
        left: Math.max(margin, Math.min(anchor.right - menu.width, window.innerWidth - margin - menu.width)),
        top: Math.max(margin, Math.min(top, window.innerHeight - margin - height)),
        maxHeight,
      };
      setPosition((current) => {
        if (current?.left === next.left && current.top === next.top && current.maxHeight === next.maxHeight) return current;
        return next;
      });
    };
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(trigger);
    observer?.observe(popup);
    return () => observer?.disconnect();
  }, [isOpen, triggerRef, popupRef]);
  useLayoutEffect(() => {
    if (!isOpen || !position || focused.current) return;
    focused.current = true;
    const target = popupRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)") ?? popupRef.current;
    target?.focus({ preventScroll: true });
  }, [isOpen, position, popupRef]);
  return position;
}
