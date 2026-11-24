import { Vector4 } from "three";

export const POINTER_TRAIL_LENGTH = 8;
export const MAX_PARTICLE_OFFSET = .14;
export const POINTER_RETURN_SECONDS = .65;

/** Bounded, frame-rate independent strokes. Stationary hover never excavates a face. */
export class HologramInteraction {
  readonly strokes = Array.from({ length: POINTER_TRAIL_LENGTH }, () => new Vector4());
  readonly energies = Array.from({ length: POINTER_TRAIL_LENGTH }, () => new Vector4(-100, 0, 0, 0));
  private previous: { x: number; y: number; at: number } | null = null;
  private index = 0;

  update(x: number, y: number, active: boolean, time: number) {
    if (!active || ![x, y, time].every(Number.isFinite)) { this.previous = null; return; }
    const previous = this.previous;
    this.previous = { x, y, at: time };
    if (!previous) return;
    const dx = x - previous.x, dy = y - previous.y, distance = Math.hypot(dx, dy);
    if (distance < .0002) return;
    const speed = distance / Math.max(1 / 120, time - previous.at);
    // Ordinary strokes are already luminous; speed adds reach and intensity.
    const gain = .38 + .62 * (1 - Math.exp(-speed * 1.8));
    this.strokes[this.index].set(previous.x, previous.y, x, y);
    this.energies[this.index].set(time, gain, dx / distance, dy / distance);
    this.index = (this.index + 1) % POINTER_TRAIL_LENGTH;
  }

  reset() {
    this.previous = null;
    for (const value of this.energies) value.set(-100, 0, 0, 0);
  }
}

export function conversationMotion(listening: boolean, responding: boolean, level: number, speechActive: boolean) {
  const voice = listening || responding || speechActive || (Number.isFinite(level) && level > .035);
  return { holdRotation: voice, ambient: voice ? .28 : 1, response: responding || speechActive ? 1 : 0 };
}
