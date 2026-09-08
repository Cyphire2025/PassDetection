import type { GeoPoint, JourneyRoute } from '../../model/journey-route';
import { arcPoint, boundedCamera, cameraForRoute, cameraMatrix, dot, geoVector, greatCircle, type Vec3 } from '../globe-math';
import { endpointMesh, planeMesh, routeTube } from '../route-mesh';

const point = (latitude: number, longitude: number): GeoPoint => ({
  city: 'Fixture', country: 'Fixture', countryCode: 'XX', latitude, longitude,
});
const project = (matrix: Float32Array, v: Vec3): Vec3 => [
  matrix[0]! * v[0] + matrix[3]! * v[1] + matrix[6]! * v[2],
  matrix[1]! * v[0] + matrix[4]! * v[1] + matrix[7]! * v[2],
  matrix[2]! * v[0] + matrix[5]! * v[1] + matrix[8]! * v[2],
];

describe('geographically anchored globe', () => {
  it('uses north-up/east-right coordinates and keeps endpoints exact', () => {
    expect(geoVector(point(0, 0))).toEqual([0, 0, 1]);
    expect(geoVector(point(90, 0))[1]).toBeCloseTo(1);
    expect(geoVector(point(0, 90))[0]).toBeCloseTo(1);
    const a = geoVector(point(28.6, 77.2));
    const b = geoVector(point(-33.87, 151.2));
    expect(greatCircle(a, b, 0)).toEqual(a);
    expect(greatCircle(a, b, 1)).toEqual(b);
    expect(dot(greatCircle(a, b, 0.5), greatCircle(a, b, 0.5))).toBeCloseTo(1);
  });

  it('crosses the antimeridian by the short route instead of wrapping through Greenwich', () => {
    const midpoint = greatCircle(geoVector(point(0, 170)), geoVector(point(0, -170)), 0.5);
    expect(midpoint[2]).toBeCloseTo(-1);
    expect(midpoint[0]).toBeCloseTo(0);
  });

  it('handles coincident and antipodal points without NaNs', () => {
    for (const destination of [point(0, 0), point(0, 180), point(0.000001, 179.99999)]) {
      for (const t of [0, 0.25, 0.5, 0.75, 1]) {
        const v = greatCircle(geoVector(point(0, 0)), geoVector(destination), t);
        expect(v.every(Number.isFinite)).toBe(true);
        expect(dot(v, v)).toBeCloseTo(1);
      }
    }
  });

  it('frames both Delhi-Sydney endpoints on the front hemisphere and rotates geography together', () => {
    const route: JourneyRoute = { key: 'fixture', origin: point(28.6, 77.2), destination: point(-33.87, 151.2),
      kind: 'illustrative', distanceKm: 10400 };
    const camera = cameraForRoute(route);
    const matrix = cameraMatrix(camera);
    const a = geoVector(route.origin);
    const b = geoVector(route.destination);
    expect(project(matrix, a)[2]).toBeGreaterThan(0.6);
    expect(project(matrix, b)[2]).toBeGreaterThan(0.6);
    const mid = project(matrix, greatCircle(a, b, 0.5));
    expect(Math.hypot(mid[0], mid[1])).toBeLessThan(0.22);
    expect(mid[2]).toBeGreaterThan(0.97);
    expect(project(cameraMatrix({ ...camera, longitude: camera.longitude + Math.PI }), a)[2]).toBeLessThan(0);
    expect(dot(arcPoint(a, b, 0.5), arcPoint(a, b, 0.5))).toBeGreaterThan(1);
  });

  it('reveals the raised arc in the initial view without pushing endpoints behind the globe', () => {
    for (const destination of [point(1.35, 103.82), point(-33.87, 151.2), point(25.2, 55.27)]) {
      const route: JourneyRoute = { key: 'arc', origin: point(28.6, 77.2), destination, kind: 'illustrative', distanceKm: 5000 };
      const a = geoVector(route.origin);
      const b = geoVector(route.destination);
      const matrix = cameraMatrix(cameraForRoute(route));
      const start = project(matrix, arcPoint(a, b, 0));
      const end = project(matrix, arcPoint(a, b, 1));
      const middle = project(matrix, arcPoint(a, b, 0.5));
      const dx = end[0] - start[0];
      const dy = end[1] - start[1];
      const distanceFromChord = Math.abs(dx * (middle[1] - start[1]) - dy * (middle[0] - start[0])) / Math.hypot(dx, dy);
      expect(distanceFromChord).toBeGreaterThan(0.015);
      expect(start[2]).toBeGreaterThan(0.55);
      expect(end[2]).toBeGreaterThan(0.55);
    }
  });

  it('bounds zoom and vertical rotation to prevent losing the Earth', () => {
    expect(boundedCamera({ longitude: 0, latitude: 9, zoom: 20 })).toEqual({ longitude: 0, latitude: 1.42, zoom: 2.4 });
    expect(boundedCamera({ longitude: 0, latitude: -9, zoom: -20 }).zoom).toBe(1);
  });

  it('keeps flight and endpoint meshes finite, including polar and coincident routes', () => {
    const a = geoVector(point(28.6, 77.2));
    for (const b of [geoVector(point(-33.87, 151.2)), geoVector(point(90, 0)), a]) {
      for (const vertices of [routeTube(a, b), endpointMesh(b, 0.04), planeMesh(a, b, 0.45)]) {
        expect(vertices.length % 9).toBe(0);
        expect(Array.from(vertices).every(Number.isFinite)).toBe(true);
      }
    }
  });
});
