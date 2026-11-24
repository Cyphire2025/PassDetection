import { clamp } from "./types";

/** Smoothed browser pointer, independent of the synthetic voice interaction. */
export class PointerField {
  x = -9999;
  y = -9999;
  vx = 0;
  vy = 0;
  presence = 0;
  private target = { x: -9999, y: -9999 };
  private previous = { x: -9999, y: -9999 };
  private present = 0;
  private releaseAt = 0;

  input(type: "move" | "down" | "up" | "leave", x: number, y: number, touch: boolean) {
    if (type === "leave" || type === "up" && touch) {
      this.present = 0;
      this.releaseAt = 0;
      return;
    }
    if (this.x < -9000) {
      this.x = this.previous.x = x;
      this.y = this.previous.y = y;
    }
    this.target = { x, y };
    this.present = 1;
    this.releaseAt = touch ? performance.now() + 300 : 0;
  }

  step(dt: number, now: number) {
    if (this.releaseAt && now > this.releaseAt) this.present = 0;
    const ease = 1 - Math.pow(.8, dt);
    this.x += (this.target.x - this.x) * ease;
    this.y += (this.target.y - this.y) * ease;
    this.vx += (clamp((this.x - this.previous.x) / dt, -32, 32) - this.vx) * ease;
    this.vy += (clamp((this.y - this.previous.y) / dt, -32, 32) - this.vy) * ease;
    this.previous = { x: this.x, y: this.y };
    this.presence += (this.present - this.presence) * (1 - Math.pow(this.present ? .86 : .92, dt));
    if (!this.present && this.presence < .001) this.presence = 0;
  }
}
