import type { ExpoWebGLRenderingContext as GL } from 'expo-gl';

import type { LandMask } from './land-asset';

type TextureProbe = { x: number; y: number; value: number };

/** Use explicit RGBA bytes on both GLES 2/3; no file decoder or format inference. */
export function prepareLandTexture(mask: LandMask, maximumSize: number) {
  if (!Number.isInteger(maximumSize) || maximumSize < 4) throw new Error('Globe texture size unavailable');
  let stride = 1;
  while (mask.width / stride > maximumSize) stride *= 2;
  const width = mask.width / stride;
  const height = mask.height / stride;
  const pixels = new Uint8Array(width * height * 4);
  let ocean: TextureProbe = { x: 0, y: 0, value: 255 };
  let land: TextureProbe = { x: 0, y: 0, value: 0 };
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let sum = 0;
      for (let sy = 0; sy < stride; sy += 1) {
        const source = (y * stride + sy) * mask.width + x * stride;
        for (let sx = 0; sx < stride; sx += 1) sum += mask.pixels[source + sx]!;
      }
      const value = Math.round(sum / (stride * stride));
      const target = (y * width + x) * 4;
      pixels[target] = pixels[target + 1] = pixels[target + 2] = value;
      pixels[target + 3] = 255;
      if (value < ocean.value) ocean = { x, y, value };
      if (value > land.value) land = { x, y, value };
    }
  }
  if (land.value - ocean.value < 128) throw new Error('Globe geography has no usable land contrast');
  return { width, height, pixels, probes: [ocean, land] };
}

/** Initial context setup only. Verify the actual uploaded texture before onReady. */
export function uploadLandTexture(gl: GL, mask: LandMask): WebGLTexture {
  const prepared = prepareLandTexture(mask, Number(gl.getParameter(gl.MAX_TEXTURE_SIZE)));
  const texture = gl.createTexture();
  if (!texture) throw new Error('Globe texture unavailable');
  let probeBuffer: WebGLFramebuffer | null = null;
  try {
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, prepared.width, prepared.height, 0,
      gl.RGBA, gl.UNSIGNED_BYTE, prepared.pixels);
    if (gl.getError() !== gl.NO_ERROR) throw new Error('Globe texture upload failed');

    probeBuffer = gl.createFramebuffer();
    if (!probeBuffer) throw new Error('Globe texture verification unavailable');
    gl.bindFramebuffer(gl.FRAMEBUFFER, probeBuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
      throw new Error('Globe texture is incomplete');
    }
    const sample = new Uint8Array(4);
    for (const probe of prepared.probes) {
      sample.fill(0);
      gl.readPixels(probe.x, probe.y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, sample);
      if (gl.getError() !== gl.NO_ERROR || sample[3] !== 255
        || sample.slice(0, 3).some((value) => Math.abs(value - probe.value) > 1)) {
        throw new Error('Globe geography did not reach the GPU');
      }
    }
    return texture;
  } catch (error) {
    gl.deleteTexture(texture);
    throw error;
  } finally {
    // ExpoGL does not implement getParameter(FRAMEBUFFER_BINDING). Initialization
    // starts on its default framebuffer; binding null restores that native target.
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (probeBuffer) gl.deleteFramebuffer(probeBuffer);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
  }
}
