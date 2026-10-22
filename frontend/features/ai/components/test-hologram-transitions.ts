type Pose = { yaw: number; pitch: number; zoom: number; landscapeYaw: number; landscapePitch: number };
const POSE_KEYS = ["yaw", "pitch", "zoom", "landscapeYaw", "landscapePitch"] as const;
const copyPose = (pose: Pose): Pose => ({ yaw: pose.yaw, pitch: pose.pitch, zoom: pose.zoom,
  landscapeYaw: pose.landscapeYaw, landscapePitch: pose.landscapePitch });

/** UI transitions use visible wall time, independently of GSAP's lag-smoothed
 * ticker and the simulation's bounded integration step. Hidden time is excluded. */
export class HologramTransitions {
  opacity = 1;
  private lastAt: number | null = null;
  private entranceElapsed: number | null = null;
  private home: { from: Pose; to: Pose; elapsed: number } | null = null;

  constructor(private readonly target: Pose) {}

  get resetting() { return this.home !== null; }

  resume(now: number) { if (this.lastAt === null) this.lastAt = now; }
  suspend() { this.lastAt = null; }
  enter() { this.opacity = 0; this.entranceElapsed = 0; }
  cancelReset() { this.home = null; }

  reset(destination: Pose, now: number) {
    // Account for the visible fraction since the previous draw before starting
    // a new transition; it must not predate the user's actual Home event.
    this.advance(now, true);
    this.home = { from: copyPose(this.target), to: copyPose(destination), elapsed: 0 };
  }

  advance(now: number, motion: boolean) {
    const elapsed = this.lastAt === null ? 0 : Math.max(0, (now - this.lastAt) / 1000);
    if (this.lastAt !== null) this.lastAt = now;
    if (!motion) {
      this.opacity = 1; this.entranceElapsed = null;
      if (this.home) Object.assign(this.target, this.home.to);
      this.home = null;
      return;
    }
    if (this.entranceElapsed !== null) {
      this.entranceElapsed = Math.min(1.2, this.entranceElapsed + elapsed);
      // Same power2.out entrance and power3.out reset as the original tweens.
      this.opacity = 1 - (1 - this.entranceElapsed / 1.2) ** 3;
      if (this.entranceElapsed === 1.2) this.entranceElapsed = null;
    }
    if (this.home) {
      this.home.elapsed = Math.min(.8, this.home.elapsed + elapsed);
      const ease = 1 - (1 - this.home.elapsed / .8) ** 4;
      for (const key of POSE_KEYS) this.target[key] = this.home.from[key] + (this.home.to[key] - this.home.from[key]) * ease;
      if (this.home.elapsed === .8) { Object.assign(this.target, this.home.to); this.home = null; }
    }
  }
}
