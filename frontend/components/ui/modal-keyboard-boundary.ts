"use client";

import { type KeyboardEvent, type RefObject, useEffect } from "react";
import { modalReturnTarget } from "./modal-focus-return";

const FOCUSABLE = 'button:not(:disabled),[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex]:not([tabindex="-1"])';
const dialogs: HTMLElement[] = [];
const inertBefore = new Map<HTMLElement, boolean>();
let bodyOverflow = "";

function focusable(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => !element.matches(":disabled") && !isHidden(element, dialog),
  );
}

function isHidden(element: HTMLElement, dialog: HTMLElement) {
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (node.hasAttribute("hidden") || node.hasAttribute("inert") || node.getAttribute("aria-hidden") === "true"
      || style.display === "none" || style.visibility === "hidden") return true;
    if (node instanceof HTMLDetailsElement && !node.open && !node.querySelector("summary")?.contains(element)) return true;
    if (node === dialog) break;
  }
  return false;
}

function focus(element: HTMLElement | undefined | null) {
  if (!element) return;
  const previous = element.getAttribute("tabindex");
  if (previous === null) element.setAttribute("tabindex", "-1");
  element.focus({ preventScroll: true });
  if (previous === null) element.removeAttribute("tabindex");
}

function focusInside(dialog: HTMLElement) {
  const available = focusable(dialog);
  focus(available.find((element) => element.hasAttribute("data-dialog-initial-focus"))
    ?? available[0] ?? dialog);
}

function isolateTopDialog() {
  for (const [element, previous] of inertBefore) element.toggleAttribute("inert", previous);
  inertBefore.clear();
  let branch = dialogs.at(-1);
  while (branch?.parentElement) {
    for (const sibling of branch.parentElement.children) {
      if (sibling === branch || !(sibling instanceof HTMLElement)) continue;
      inertBefore.set(sibling, sibling.hasAttribute("inert"));
      sibling.setAttribute("inert", "");
    }
    branch = branch.parentElement;
    if (branch === document.body) break;
  }
}

/** One active keyboard boundary, including nested dialogs and removed triggers. */
export function useModalKeyboardBoundary<T extends HTMLElement>({ dialogRef, isOpen, canClose, onClose }: {
  dialogRef: RefObject<T | null>;
  isOpen: boolean;
  canClose: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!isOpen || !dialog) return;
    const trigger = modalReturnTarget(dialog);
    if (dialogs.length === 0) bodyOverflow = document.body.style.overflow;
    // Child effects can run first; an ancestor must never replace its nested dialog.
    const childIndex = dialogs.findIndex((entry) => dialog.contains(entry));
    if (childIndex < 0) dialogs.push(dialog);
    else dialogs.splice(childIndex, 0, dialog);
    isolateTopDialog();
    document.body.style.overflow = "hidden";
    if (dialogs.at(-1) === dialog) focusInside(dialog);
    const containFocus = (event: FocusEvent) => {
      if (dialogs.at(-1) === dialog && event.target instanceof Node && !dialog.contains(event.target)) {
        focusInside(dialog);
      }
    };
    document.addEventListener("focusin", containFocus);
    return () => {
      document.removeEventListener("focusin", containFocus);
      const wasTop = dialogs.at(-1) === dialog;
      dialogs.splice(dialogs.indexOf(dialog), 1);
      isolateTopDialog();
      if (dialogs.length === 0) document.body.style.overflow = bodyOverflow;
      if (!wasTop) return;
      const top = dialogs.at(-1);
      if (trigger?.isConnected && !trigger.closest("[inert]") && (!top || top.contains(trigger))) focus(trigger);
      else if (top) focusInside(top);
      else focus(document.querySelector<HTMLElement>("[data-dialog-focus-fallback],main") ?? document.body);
    };
  }, [dialogRef, isOpen]);

  return (event: KeyboardEvent<T>) => {
    const dialog = dialogRef.current;
    if (!dialog || dialogs.at(-1) !== dialog) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (canClose) onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const available = focusable(dialog);
    const first = available[0];
    const last = available.at(-1);
    if (!first || !available.includes(document.activeElement as HTMLElement)) {
      event.preventDefault();
      focus(event.shiftKey ? last ?? dialog : first ?? dialog);
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      focus(last);
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      focus(first);
    }
  };
}
