export type LauncherOrigin = { x: number; y: number; radius: number };
const ORIGIN_KEY = "gc-assistant-launcher-origin";

export function rememberLauncher(element: HTMLElement) {
  const bounds = element.getBoundingClientRect();
  const origin: LauncherOrigin = { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2, radius: bounds.width / 2 };
  try { sessionStorage.setItem(ORIGIN_KEY, JSON.stringify(origin)); } catch { /* Animation also works without browser storage. */ }
}

export function launcherOrigin(): LauncherOrigin {
  const element = document.querySelector<HTMLElement>("[data-assistant-launcher]");
  if (element) {
    const bounds = element.getBoundingClientRect();
    return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2, radius: bounds.width / 2 };
  }
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) || "null");
    if (stored && typeof stored === "object" && "x" in stored && "y" in stored && "radius" in stored
      && typeof stored.x === "number" && typeof stored.y === "number" && typeof stored.radius === "number"
      && Number.isFinite(stored.x) && Number.isFinite(stored.y) && stored.x >= 0 && stored.x <= innerWidth && stored.y >= 0 && stored.y <= innerHeight) return { x: stored.x, y: stored.y, radius: Math.min(40, Math.max(12, stored.radius)) };
  } catch { /* Use the normal top-navigation position. */ }
  return { x: innerWidth - 200, y: 34, radius: 22 };
}

export function animateWorkspace(element: HTMLElement, closing: boolean): Animation | null {
  if (typeof element.animate !== "function") return null;
  const origin = launcherOrigin();
  const expanded = Math.hypot(Math.max(origin.x, innerWidth - origin.x), Math.max(origin.y, innerHeight - origin.y)) + 20;
  const small = `circle(${origin.radius}px at ${origin.x}px ${origin.y}px)`;
  const full = `circle(${expanded}px at ${origin.x}px ${origin.y}px)`;
  return element.animate([{ clipPath: closing ? full : small }, { clipPath: closing ? small : full }], {
    duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : closing ? 650 : 850,
    easing: "cubic-bezier(.22,1,.36,1)", fill: "forwards",
  });
}
