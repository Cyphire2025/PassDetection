import type { ParticleDisplacement } from "./test-hologram-displacement";

const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? 0;
const distance = (a: number[], b: number[]) => Math.hypot(...a.map((value, axis) => value - b[axis]));

/** Persistent GPU texel identities must travel through space while the density
 * distribution remains a head. Neither seed offsets nor model yaw count as flow. */
export function volumeTransport(frames: ParticleDisplacement[]) {
  if (frames.length < 2) throw new Error("Transport requires multiple real GPU frames");
  const first = frames[0], last = frames.at(-1)!;
  const maps = frames.map((frame) => new Map(frame.identities.map((particle) => [particle.id, particle])));
  const paths = first.identities.flatMap((particle) => {
    const track = maps.map((map) => map.get(particle.id));
    if (track.some((point) => !point)) return [];
    const points = track.map((point) => point!);
    const path = points.slice(1).reduce((sum, point, index) => sum + distance(point.position, points[index].position), 0);
    const net = distance(particle.position, points.at(-1)!.position);
    const cells = new Set(points.map((point) => point.position.map((value) => Math.floor(value / .12)).join(",")));
    const deep = particle.distance < -2 * first.sdf.voxel;
    const front = particle.canonical[2] > .25 && Math.abs(particle.canonical[0]) < .42
      && particle.canonical[1] > -.45 && particle.canonical[1] < .65 && Math.abs(particle.distance) < first.sdf.voxel * 1.5;
    return [{ id: particle.id, deep, front, path, net, cells: cells.size,
      screenNet: distance(particle.screen, points.at(-1)!.screen), efficiency: net / Math.max(path, 1e-12) }];
  });
  const summarize = (items: typeof paths) => ({ count: items.length,
    medianNet: median(items.map((item) => item.net)), medianPath: median(items.map((item) => item.path)),
    transported: items.filter((item) => item.net > .25 && item.cells >= 3).length,
    visibleTransport: items.filter((item) => item.screenNet > 10).length,
    medianEfficiency: median(items.map((item) => item.efficiency)) });
  const distributionChange = frames.map((frame) => frame.shape.bins.reduce((sum, count, index) =>
    sum + Math.abs(count / frame.samples - first.shape.bins[index] / first.samples), 0) / 2);
  return { seconds: last.time - first.time, all: summarize(paths), deep: summarize(paths.filter((item) => item.deep)),
    front: summarize(paths.filter((item) => item.front)), maximumDensityChange: Math.max(...distributionChange), distributionChange, paths };
}
