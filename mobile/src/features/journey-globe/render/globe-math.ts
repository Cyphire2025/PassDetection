import type { GeoPoint, JourneyRoute } from '../model/journey-route';

export type Vec3 = readonly [number, number, number];
export type GlobeCamera = { longitude: number; latitude: number; zoom: number };
const DEG = Math.PI / 180;

export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
export const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const multiply = (v: Vec3, n: number): Vec3 => [v[0] * n, v[1] * n, v[2] * n];
export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0],
];
export const normalize = (v: Vec3): Vec3 => multiply(v, 1 / Math.max(1e-9, Math.sqrt(dot(v, v))));

/** +Y north; Greenwich faces +Z; eastern longitudes turn toward +X. */
export function geoVector(point: Pick<GeoPoint, 'latitude' | 'longitude'>): Vec3 {
  const lat = point.latitude * DEG;
  const lon = point.longitude * DEG;
  return [Math.cos(lat) * Math.sin(lon), Math.sin(lat), Math.cos(lat) * Math.cos(lon)];
}

/** Shortest great-circle interpolation, including the antimeridian and near antipodes. */
export function greatCircle(a: Vec3, b: Vec3, progress: number): Vec3 {
  const t = clamp(progress, 0, 1);
  if (t === 0) return a;
  if (t === 1) return b;
  const cosine = clamp(dot(a, b), -1, 1);
  if (cosine > 0.99999) return normalize(add(multiply(a, 1 - t), multiply(b, t)));
  const angle = Math.acos(cosine);
  const orthogonal = add(b, multiply(a, -cosine));
  // Exact antipodes have no unique shortest arc: choose a stable perpendicular.
  const tangent = dot(orthogonal, orthogonal) < 1e-12
    ? normalize(cross(a, Math.abs(a[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]))
    : normalize(orthogonal);
  return normalize(add(multiply(a, Math.cos(angle * t)), multiply(tangent, Math.sin(angle * t))));
}

export function arcPoint(a: Vec3, b: Vec3, progress: number): Vec3 {
  return multiply(greatCircle(a, b, progress), 1.014 + Math.sin(Math.PI * progress) * 0.15);
}

export function cameraForRoute(route: JourneyRoute | null): GlobeCamera {
  let midpoint = route ? greatCircle(geoVector(route.origin), geoVector(route.destination), 0.5)
    : geoVector({ latitude: 18, longitude: 80 });
  if (route) {
    const a = geoVector(route.origin);
    const b = geoVector(route.destination);
    const perpendicular = cross(a, b);
    if (dot(perpendicular, perpendicular) > 1e-9) {
      // Looking exactly along the route plane flattens an elevated arc into a
      // straight line. A small perpendicular viewing offset reveals its depth.
      // It affects both endpoints equally and tapers to zero near antipodes.
      const offset = 12 * DEG * Math.sqrt(Math.max(0, (1 + dot(a, b)) / 2));
      midpoint = normalize(add(multiply(midpoint, Math.cos(offset)), multiply(normalize(perpendicular), Math.sin(offset))));
    }
  }
  return {
    longitude: Math.atan2(midpoint[0], midpoint[2]),
    latitude: Math.asin(clamp(midpoint[1], -1, 1)),
    zoom: 1,
  };
}

/** Column-major matrix converting world positions into the camera's orthographic frame. */
export function cameraMatrix(camera: GlobeCamera): Float32Array {
  const { longitude: lon, latitude: lat } = camera;
  const right: Vec3 = [Math.cos(lon), 0, -Math.sin(lon)];
  const up: Vec3 = [-Math.sin(lat) * Math.sin(lon), Math.cos(lat), -Math.sin(lat) * Math.cos(lon)];
  const forward = geoVector({ latitude: lat / DEG, longitude: lon / DEG });
  return new Float32Array([
    right[0], up[0], forward[0], right[1], up[1], forward[1], right[2], up[2], forward[2],
  ]);
}

export function boundedCamera(camera: GlobeCamera): GlobeCamera {
  // Do not wrap longitude at +/-2PI: that would reverse an in-progress drag.
  return { longitude: camera.longitude, latitude: clamp(camera.latitude, -1.42, 1.42), zoom: clamp(camera.zoom, 1, 2.4) };
}
