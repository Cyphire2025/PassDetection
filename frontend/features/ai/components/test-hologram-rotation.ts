export const IDLE_ROTATION_SPEED = .22;
export const SPEECH_ROTATION_HOLD = .9;
const RESUME_RATE = 1 / .6;

/** Idle rotation is independent of the simulation and audible articulation. */
export class HologramRotation {
  private angle = 0;
  private speed = 0;
  private hold = 0;

  advance(elapsed: number, motion: boolean, speaking: boolean, manipulating = false) {
    if (!motion) { this.speed = 0; return this.angle; }
    if (speaking || manipulating) {
      this.hold = SPEECH_ROTATION_HOLD; this.speed = 0;
      return this.angle;
    }
    // A suspended renderer supplies zero elapsed time; a long main-thread stall
    // must not fast-forward a full revolution on the next visible frame.
    const dt = Math.min(.5, Math.max(0, elapsed));
    const active = Math.max(0, dt - this.hold);
    this.hold = Math.max(0, this.hold - dt);
    const decay = Math.exp(-active * RESUME_RATE);
    this.angle += IDLE_ROTATION_SPEED * active + (this.speed - IDLE_ROTATION_SPEED) * (1 - decay) / RESUME_RATE;
    this.speed = IDLE_ROTATION_SPEED + (this.speed - IDLE_ROTATION_SPEED) * decay;
    this.angle %= Math.PI * 2;
    return this.angle;
  }

  /** Transfer this angle into manual view before a smooth shortest-arc reset. */
  reset() {
    const angle = this.angle;
    this.angle = 0; this.speed = 0; this.hold = 1.2;
    return angle;
  }
}
