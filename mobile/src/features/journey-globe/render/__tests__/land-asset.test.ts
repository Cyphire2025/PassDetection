import { base64 } from '@scure/base';

import { decodeLandMask, loadLandMask } from '../land-asset';

const packed = (runs: number[]) => ({
  encoding: 'rle8-v1', width: 4, height: 2, data: base64.encode(new Uint8Array(runs)),
});

describe('offline globe geography pixels', () => {
  it('losslessly expands antialiased pixels, including both land and ocean', () => {
    const mask = decodeLandMask(packed([0, 0, 2, 255, 0, 2, 73, 0, 4]));
    expect(mask).toEqual({ width: 4, height: 2, pixels: new Uint8Array([0, 0, 255, 255, 73, 73, 73, 73]) });
  });

  it('shares one decoded mask between the card and expanded globe', () => {
    const mask = loadLandMask();
    expect(loadLandMask()).toBe(mask);
    expect([mask.width, mask.height, mask.pixels.length]).toEqual([2048, 1024, 2097152]);
  });

  it.each([
    ['Africa', 20, 20], ['Europe', 52, 13], ['Asia', 22, 78],
    ['Australia', -25, 134], ['North America', 40, -100],
    ['South America', -10, -60], ['Antarctica', -85, 0],
  ])('bundles real land in %s with the same coordinate orientation as the shader', (_name, latitude, longitude) => {
    const mask = loadLandMask();
    const x = Math.floor((Number(longitude) + 180) / 360 * mask.width);
    const y = Math.floor((90 - Number(latitude)) / 180 * mask.height);
    expect(mask.pixels[y * mask.width + x]).toBeGreaterThan(230);
  });

  it.each([[-140, 0], [-30, 0], [80, -30]])('retains ocean at longitude %s, latitude %s', (longitude, latitude) => {
    const mask = loadLandMask();
    const x = Math.floor((longitude + 180) / 360 * mask.width);
    const y = Math.floor((90 - latitude) / 180 * mask.height);
    expect(mask.pixels[y * mask.width + x]).toBeLessThan(20);
  });

  it.each([
    [], [0, 0], [0, 0, 0], [255, 0, 9], [255, 0, 2], [0, 0, 8], [255, 0, 8],
  ].map((runs) => ({ runs })))('rejects malformed or empty geography (%j)', ({ runs }) => {
    expect(() => decodeLandMask(packed(runs))).toThrow();
  });

  it.each([
    { width: 0 }, { width: 4096, height: 2048 }, { width: 7 },
    { height: 3 }, { encoding: 'unknown' }, { data: '!!!' },
  ])('rejects unsupported metadata or encoding (%j)', (override) => {
    expect(() => decodeLandMask({ ...packed([0, 0, 6, 255, 0, 2]), ...override })).toThrow();
  });
});
