import type { ExpoWebGLRenderingContext as GL } from 'expo-gl';

import { loadLandMask, type LandMask } from '../land-asset';
import { prepareLandTexture, uploadLandTexture } from '../land-texture';

const mask: LandMask = { width: 4, height: 2, pixels: new Uint8Array([0, 255, 73, 0, 0, 255, 0, 0]) };

function mockContext() {
  let uploaded = new Uint8Array();
  let width = 0;
  const texture = {} as WebGLTexture;
  const framebuffer = {} as WebGLFramebuffer;
  const context = {
    NO_ERROR: 0, MAX_TEXTURE_SIZE: 3379, TEXTURE0: 33984, TEXTURE_2D: 3553,
    TEXTURE_MIN_FILTER: 10241, TEXTURE_MAG_FILTER: 10240, TEXTURE_WRAP_S: 10242, TEXTURE_WRAP_T: 10243,
    LINEAR: 9729, CLAMP_TO_EDGE: 33071, UNPACK_ALIGNMENT: 3317, UNPACK_FLIP_Y_WEBGL: 37440,
    RGBA: 6408, UNSIGNED_BYTE: 5121, FRAMEBUFFER: 36160, COLOR_ATTACHMENT0: 36064, FRAMEBUFFER_COMPLETE: 36053,
    getParameter: jest.fn(() => 2048), createTexture: jest.fn(() => texture), deleteTexture: jest.fn(),
    activeTexture: jest.fn(), bindTexture: jest.fn(), texParameteri: jest.fn(), pixelStorei: jest.fn(),
    texImage2D: jest.fn((...args: unknown[]) => { width = Number(args[3]); uploaded = args[8] as Uint8Array<ArrayBuffer>; }),
    getError: jest.fn(() => 0), createFramebuffer: jest.fn(() => framebuffer), deleteFramebuffer: jest.fn(),
    bindFramebuffer: jest.fn(), framebufferTexture2D: jest.fn(), checkFramebufferStatus: jest.fn(() => 36053),
    readPixels: jest.fn((x: number, y: number, _w: number, _h: number, _format: number, _type: number, target: Uint8Array) => {
      target.set(uploaded.subarray((y * width + x) * 4, (y * width + x) * 4 + 4));
    }),
  };
  return { context, gl: context as unknown as GL, texture, framebuffer };
}

describe('portable globe texture upload', () => {
  it('uploads opaque RGBA with explicit dimensions and validates real land and ocean pixels', () => {
    const { context, gl, texture, framebuffer } = mockContext();
    expect(uploadLandTexture(gl, mask)).toBe(texture);
    const call = context.texImage2D.mock.calls[0]!;
    expect(call).toHaveLength(9);
    expect(call.slice(0, 8)).toEqual([gl.TEXTURE_2D, 0, gl.RGBA, 4, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE]);
    expect(Array.from((call[8] as Uint8Array).slice(0, 12))).toEqual([0, 0, 0, 255, 255, 255, 255, 255, 73, 73, 73, 255]);
    expect(context.readPixels).toHaveBeenCalledTimes(2);
    expect(context.activeTexture).toHaveBeenCalledWith(gl.TEXTURE0);
    expect(context.bindFramebuffer).toHaveBeenLastCalledWith(gl.FRAMEBUFFER, null);
    expect(context.deleteFramebuffer).toHaveBeenCalledWith(framebuffer);
    expect(context.deleteTexture).not.toHaveBeenCalled();
    expect(context.getParameter).toHaveBeenCalledTimes(1);
    expect(context.getParameter).toHaveBeenCalledWith(gl.MAX_TEXTURE_SIZE);
  });

  it('preserves coastlines when fitting a smaller GPU texture limit', () => {
    const pixels = new Uint8Array([
      0, 0, 0, 255, 255, 255, 255, 255,
      0, 0, 255, 0, 255, 255, 255, 255,
      0, 0, 0, 0, 255, 255, 0, 0,
      0, 0, 0, 0, 255, 255, 0, 0,
    ]);
    const prepared = prepareLandTexture({ width: 8, height: 4, pixels }, 6);
    expect([prepared.width, prepared.height]).toEqual([4, 2]);
    expect(Array.from(prepared.pixels.filter((_value, index) => index % 4 === 0))).toEqual([0, 128, 255, 255, 0, 0, 255, 0]);
    expect(pixels[3]).toBe(255);
  });

  it('fits the bundled world into a lower-resolution texture without losing its continents', () => {
    const prepared = prepareLandTexture(loadLandMask(), 1024);
    expect([prepared.width, prepared.height, prepared.pixels.length]).toEqual([1024, 512, 2097152]);
    expect(prepared.probes.map((probe) => probe.value)).toEqual([0, 255]);
    const x = Math.floor((134 + 180) / 360 * prepared.width);
    const y = Math.floor((90 + 25) / 180 * prepared.height);
    expect(prepared.pixels[(y * prepared.width + x) * 4]).toBe(255);
  });

  it.each([0, NaN, 2.5])('rejects an unusable driver limit %s before allocating GL resources', (limit) => {
    const { context, gl } = mockContext();
    context.getParameter.mockReturnValue(limit);
    expect(() => uploadLandTexture(gl, mask)).toThrow('size unavailable');
    expect(context.createTexture).not.toHaveBeenCalled();
  });

  it('does not accept a silent all-black upload as a ready globe', () => {
    const { context, gl, texture, framebuffer } = mockContext();
    context.readPixels.mockImplementation((_x, _y, _w, _h, _f, _t, target) => { target.set([0, 0, 0, 255]); });
    expect(() => uploadLandTexture(gl, mask)).toThrow('did not reach the GPU');
    expect(context.deleteTexture).toHaveBeenCalledWith(texture);
    expect(context.deleteFramebuffer).toHaveBeenCalledWith(framebuffer);
    expect(context.bindFramebuffer).toHaveBeenLastCalledWith(gl.FRAMEBUFFER, null);
  });

  it('cleans up after a driver upload error', () => {
    const { context, gl, texture } = mockContext();
    context.getError.mockReturnValueOnce(1285);
    expect(() => uploadLandTexture(gl, mask)).toThrow('upload failed');
    expect(context.deleteTexture).toHaveBeenCalledWith(texture);
    expect(context.createFramebuffer).not.toHaveBeenCalled();
    expect(context.bindFramebuffer).toHaveBeenLastCalledWith(gl.FRAMEBUFFER, null);
  });

  it('cleans up when the uploaded texture is incomplete', () => {
    const { context, gl, texture, framebuffer } = mockContext();
    context.checkFramebufferStatus.mockReturnValueOnce(36054);
    expect(() => uploadLandTexture(gl, mask)).toThrow('texture is incomplete');
    expect(context.deleteTexture).toHaveBeenCalledWith(texture);
    expect(context.deleteFramebuffer).toHaveBeenCalledWith(framebuffer);
    expect(context.readPixels).not.toHaveBeenCalled();
  });

  it('cleans up after a readback error instead of leaving a private framebuffer bound', () => {
    const { context, gl, texture, framebuffer } = mockContext();
    context.readPixels.mockImplementation(() => { throw new Error('lost context'); });
    expect(() => uploadLandTexture(gl, mask)).toThrow('lost context');
    expect(context.deleteTexture).toHaveBeenCalledWith(texture);
    expect(context.deleteFramebuffer).toHaveBeenCalledWith(framebuffer);
    expect(context.bindFramebuffer).toHaveBeenLastCalledWith(gl.FRAMEBUFFER, null);
  });
});
