import type { ExpoWebGLRenderingContext as GL } from 'expo-gl';

import type { JourneyRoute } from '../../model/journey-route';
import type { LandMask } from '../land-asset';

export const testLand: LandMask = { width: 4, height: 2, pixels: new Uint8Array([0, 255, 73, 0, 0, 255, 0, 0]) };
export const testRoute: JourneyRoute = {
  key: 'test-route', kind: 'illustrative', distanceKm: 3000,
  origin: { city: 'Delhi', country: 'India', countryCode: 'IN', latitude: 28.6, longitude: 77.2 },
  destination: { city: 'Dubai', country: 'UAE', countryCode: 'AE', latitude: 25.2, longitude: 55.3 },
};

/** Exercises the real shader, buffer, texture and route renderer paths. */
export function globeTestContext() {
  let uploaded = new Uint8Array();
  let width = 0;
  const context = {
    drawingBufferWidth: 246, drawingBufferHeight: 246,
    NO_ERROR: 0, MAX_TEXTURE_SIZE: 3379, TEXTURE0: 33984, TEXTURE_2D: 3553,
    TEXTURE_MIN_FILTER: 10241, TEXTURE_MAG_FILTER: 10240, TEXTURE_WRAP_S: 10242, TEXTURE_WRAP_T: 10243,
    LINEAR: 9729, CLAMP_TO_EDGE: 33071, UNPACK_ALIGNMENT: 3317, UNPACK_FLIP_Y_WEBGL: 37440,
    RGBA: 6408, UNSIGNED_BYTE: 5121, FRAMEBUFFER: 36160, COLOR_ATTACHMENT0: 36064, FRAMEBUFFER_COMPLETE: 36053,
    VERTEX_SHADER: 35633, FRAGMENT_SHADER: 35632, COMPILE_STATUS: 35713, LINK_STATUS: 35714,
    ARRAY_BUFFER: 34962, DYNAMIC_DRAW: 35048, STATIC_DRAW: 35044, FLOAT: 5126, TRIANGLES: 4,
    DEPTH_TEST: 2929, CULL_FACE: 2884, BLEND: 3042, SRC_ALPHA: 770, ONE_MINUS_SRC_ALPHA: 771, COLOR_BUFFER_BIT: 16384,
    createProgram: jest.fn(() => ({} as WebGLProgram)), deleteProgram: jest.fn(),
    createShader: jest.fn(() => ({} as WebGLShader)), deleteShader: jest.fn(),
    shaderSource: jest.fn(), compileShader: jest.fn(), getShaderParameter: jest.fn(() => true),
    attachShader: jest.fn(), linkProgram: jest.fn(), getProgramParameter: jest.fn(() => true),
    createBuffer: jest.fn<WebGLBuffer | null, []>(() => ({} as WebGLBuffer)), deleteBuffer: jest.fn(),
    bindBuffer: jest.fn(), bufferData: jest.fn(), bufferSubData: jest.fn(),
    getParameter: jest.fn(() => 2048), createTexture: jest.fn(() => ({} as WebGLTexture)), deleteTexture: jest.fn(),
    activeTexture: jest.fn(), bindTexture: jest.fn(), texParameteri: jest.fn(), pixelStorei: jest.fn(),
    texImage2D: jest.fn((...args: unknown[]) => { width = Number(args[3]); uploaded = args[8] as Uint8Array<ArrayBuffer>; }),
    getError: jest.fn(() => 0), createFramebuffer: jest.fn(() => ({} as WebGLFramebuffer)), deleteFramebuffer: jest.fn(),
    bindFramebuffer: jest.fn(), framebufferTexture2D: jest.fn(), checkFramebufferStatus: jest.fn(() => 36053),
    readPixels: jest.fn((x: number, y: number, _w: number, _h: number, _format: number, _type: number, target: Uint8Array) => {
      target.set(uploaded.subarray((y * width + x) * 4, (y * width + x) * 4 + 4));
    }),
    getUniformLocation: jest.fn(() => ({} as WebGLUniformLocation)), getAttribLocation: jest.fn(() => 0),
    uniformMatrix3fv: jest.fn(), uniform2f: jest.fn(), uniform1f: jest.fn(), uniform1i: jest.fn(), uniform4f: jest.fn(),
    viewport: jest.fn(), disable: jest.fn(), enable: jest.fn(), blendFunc: jest.fn(), clearColor: jest.fn(), clear: jest.fn(),
    useProgram: jest.fn(), enableVertexAttribArray: jest.fn(), vertexAttribPointer: jest.fn(), drawArrays: jest.fn(),
    disableVertexAttribArray: jest.fn(), flush: jest.fn(), endFrameEXP: jest.fn(),
  };
  return { context, gl: context as unknown as GL };
}
