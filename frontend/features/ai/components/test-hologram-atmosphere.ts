/** Small camera offsets keep the original composition readable at every pointer position. */
export function atmosphereView(time: number, pointerX: number, pointerY: number, motion: boolean) {
  if (!motion) return { yaw: 0, pitch: 0 };
  const unit = (value: number) => Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0;
  const clock = Number.isFinite(time) ? time : 0;
  return {
    yaw: -unit(pointerX) * .018 + Math.sin(clock * .13) * .004,
    pitch: unit(pointerY) * .009 + Math.sin(clock * .17) * .0025,
  };
}

/** Listening drives the snow, while only actual playback drives the mouth. */
export function sculptureEnergy(level: number, playback: number, motion: boolean): number {
  if (!motion) return 0;
  const unit = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
  return Math.max(unit(level), unit(playback));
}
