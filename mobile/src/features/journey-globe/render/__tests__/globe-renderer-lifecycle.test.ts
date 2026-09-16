import { createBuffer, createProgram } from '../gl-program';
import { createGlobeRenderer } from '../globe-renderer';
import { globeTestContext, testLand, testRoute } from './globe-test-context';

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

test('disposes partially created renderer when the first vertex allocation fails', () => {
  const { gl, context } = globeTestContext();
  context.createBuffer.mockReturnValue(null);
  expect(() => createGlobeRenderer(gl, testLand, 'card')).toThrow('Globe vertex buffer unavailable');
  expect(context.deleteProgram).toHaveBeenCalledTimes(2);
  expect(context.deleteShader).toHaveBeenCalledTimes(4);
});

test('route allocation failure remains disposable even when native resource deletion also fails', () => {
  const { gl, context } = globeTestContext();
  const renderer = createGlobeRenderer(gl, testLand, 'card');
  renderer.setRoute(testRoute);
  context.createBuffer.mockReturnValueOnce({} as WebGLBuffer).mockReturnValueOnce(null);
  expect(() => renderer.setRoute({ ...testRoute, key: 'updated' })).toThrow('Globe vertex buffer unavailable');
  const deletedBeforeDisposal = context.deleteBuffer.mock.calls.length;
  context.deleteBuffer.mockImplementationOnce(() => { throw new Error('native context destroyed'); });
  expect(() => renderer.dispose()).not.toThrow();
  expect(context.deleteBuffer.mock.calls.length - deletedBeforeDisposal).toBe(3);
  expect(context.deleteProgram).toHaveBeenCalledTimes(2);
  expect(context.deleteTexture).toHaveBeenCalledTimes(1);
  const drawCount = context.drawArrays.mock.calls.length;
  renderer.renderStill();
  renderer.dispose();
  expect(context.drawArrays).toHaveBeenCalledTimes(drawCount);
  expect(context.deleteProgram).toHaveBeenCalledTimes(2);
});

test('a failed buffer upload releases its allocation and preserves the original failure', () => {
  const { gl, context } = globeTestContext();
  const failure = new Error('buffer upload failed');
  context.bufferData.mockImplementation(() => { throw failure; });
  context.deleteBuffer.mockImplementation(() => { throw new Error('already destroyed'); });
  expect(() => createBuffer(gl, new Float32Array(3))).toThrow(failure);
  expect(context.deleteBuffer).toHaveBeenCalledTimes(1);
});

test('shader cleanup cannot hide a successful program or prevent subsequent resource tracking', () => {
  const { gl, context } = globeTestContext();
  context.deleteShader.mockImplementationOnce(() => { throw new Error('shader context gone'); });
  const renderer = createGlobeRenderer(gl, testLand, 'card');
  expect(context.deleteShader).toHaveBeenCalledTimes(4);
  renderer.dispose();
  expect(context.deleteProgram).toHaveBeenCalledTimes(2);
});

test('failed program cleanup preserves its original error and attempts every shader release', () => {
  const { gl, context } = globeTestContext();
  context.getProgramParameter.mockReturnValue(false);
  context.deleteProgram.mockImplementation(() => { throw new Error('native program unavailable'); });
  context.deleteShader.mockImplementationOnce(() => { throw new Error('native shader unavailable'); });
  expect(() => createProgram(gl, 'vertex', 'fragment')).toThrow('Globe shader could not link');
  expect(context.deleteShader).toHaveBeenCalledTimes(2);
});

test('a failed animation frame stops, cleans all resources and reports once', () => {
  const { gl, context } = globeTestContext();
  const onError = jest.fn();
  let nextFrame: FrameRequestCallback | undefined;
  jest.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((callback) => { nextFrame = callback; return 1; });
  const renderer = createGlobeRenderer(gl, testLand, 'card', onError);
  renderer.setRoute(testRoute);
  renderer.setActive(true);
  context.drawArrays.mockImplementation(() => { throw new Error('surface gone'); });
  context.deleteBuffer.mockImplementationOnce(() => { throw new Error('native context destroyed'); });
  expect(() => nextFrame?.(16)).not.toThrow();
  nextFrame?.(32);
  expect(onError).toHaveBeenCalledTimes(1);
  expect(context.deleteTexture).toHaveBeenCalledTimes(1);
  expect(context.deleteProgram).toHaveBeenCalledTimes(2);
});
