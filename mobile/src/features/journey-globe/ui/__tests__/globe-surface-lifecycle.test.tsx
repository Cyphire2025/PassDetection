import { act, fireEvent, render, screen } from '@testing-library/react-native';
import type { ExpoWebGLRenderingContext } from 'expo-gl';
import { createRef } from 'react';
import { AppState, Text, View, type AppStateStatus } from 'react-native';

import type { JourneyRoute } from '../../model/journey-route';
import * as rendererModule from '../../render/globe-renderer';
import { globeTestContext, testRoute } from '../../render/__tests__/globe-test-context';
import { GlobeSurface, type GlobeSurfaceHandle } from '../globe-surface';

jest.mock('expo-gl', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const NativeView = jest.requireActual<typeof import('react-native')>('react-native').View;
  return { GLView: ({ onContextCreate }: { onContextCreate: (gl: ExpoWebGLRenderingContext) => void }) =>
    React.createElement(NativeView, { testID: 'native-gl-view', ...{ onContextCreate } }) };
});
jest.mock('../../render/land-asset', () => ({
  loadLandMask: () => jest.requireActual('../../render/__tests__/globe-test-context').testLand,
}));
jest.mock('react-native-gesture-handler', () => {
  const NativeView = jest.requireActual<typeof import('react-native')>('react-native').View;
  const gesture = () => {
    const chain = { enabled: () => chain, minDistance: () => chain, maxPointers: () => chain,
      runOnJS: () => chain, onChange: () => chain, onBegin: () => chain, onUpdate: () => chain };
    return chain;
  };
  return { GestureDetector: NativeView, Gesture: { Pan: gesture, Pinch: gesture, Simultaneous: jest.fn() } };
});

let appStateListener: (state: AppStateStatus) => void;
const nativeView = () => screen.getByTestId('native-gl-view', { includeHiddenElements: true });
const nativeCallback = () => nativeView().props.onContextCreate as (gl: ExpoWebGLRenderingContext) => void;

beforeEach(() => {
  jest.useFakeTimers();
  AppState.currentState = 'active';
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_name, listener) => {
    appStateListener = listener;
    return { remove: jest.fn() };
  });
});
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

test('a real post-ready route buffer failure falls back without interrupting adjacent trip content', async () => {
  const { gl, context } = globeTestContext();
  const onError = jest.fn(); const onReady = jest.fn();
  const surface = (route: JourneyRoute | null) => <View>
    <Text>Trip documents remain available</Text>
    <GlobeSurface route={route} mode="card" active reduceMotion onReady={onReady} onError={onError} />
  </View>;
  const result = await render(surface(null));
  await fireEvent(nativeView(), 'contextCreate', gl);
  expect(onReady).toHaveBeenCalledTimes(1);
  context.createBuffer.mockReturnValueOnce(null);
  context.deleteBuffer.mockImplementationOnce(() => { throw new Error('native context already destroyed'); });
  await result.rerender(surface(testRoute));
  expect(onError).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Trip documents remain available')).toBeOnTheScreen();
  expect(screen.queryByTestId('native-gl-view', { includeHiddenElements: true })).toBeNull();
  expect(context.deleteProgram).toHaveBeenCalledTimes(2);
  expect(context.deleteTexture).toHaveBeenCalledTimes(1);
  await result.rerender(surface({ ...testRoute, key: 'later-refresh' }));
  expect(onError).toHaveBeenCalledTimes(1);
});

test('route failure still falls back when the entire renderer dispose method rejects', async () => {
  const { gl } = globeTestContext();
  const actual = rendererModule.createGlobeRenderer;
  jest.spyOn(rendererModule, 'createGlobeRenderer').mockImplementation((...args) => {
    const view = actual(...args);
    const setRoute = view.setRoute;
    return { ...view,
      setRoute: (route) => { if (route) throw new Error('Globe vertex buffer unavailable'); setRoute(route); },
      dispose: () => { view.dispose(); throw new Error('disposed context'); },
    };
  });
  const onError = jest.fn();
  const result = await render(<GlobeSurface route={null} mode="card" active reduceMotion onError={onError} />);
  await fireEvent(nativeView(), 'contextCreate', gl);
  await result.rerender(<GlobeSurface route={testRoute} mode="card" active reduceMotion onError={onError} />);
  expect(onError).toHaveBeenCalledTimes(1);
  await result.unmount();
  expect(onError).toHaveBeenCalledTimes(1);
});

test('background releases synchronously and foreground creates a fresh context with the current route', async () => {
  const first = globeTestContext(); const second = globeTestContext();
  const onError = jest.fn(); const onReady = jest.fn();
  const surface = (route: JourneyRoute | null) => <GlobeSurface route={route} mode="card" active reduceMotion onError={onError} onReady={onReady} />;
  const result = await render(surface(null));
  const staleCreate = nativeCallback();
  await act(async () => { staleCreate(first.gl); });
  await act(async () => { appStateListener('background'); });
  expect(first.context.deleteTexture).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId('native-gl-view', { includeHiddenElements: true })).toBeNull();
  await result.rerender(surface(testRoute));
  await act(async () => { staleCreate(first.gl); });
  expect(first.context.createBuffer).toHaveBeenCalledTimes(2);
  await act(async () => { appStateListener('active'); });
  expect(nativeCallback()).not.toBe(staleCreate);
  await fireEvent(nativeView(), 'contextCreate', second.gl);
  expect(second.context.createBuffer).toHaveBeenCalledTimes(7);
  expect(onReady).toHaveBeenCalledTimes(2);
  expect(onError).not.toHaveBeenCalled();
});

test('batched background and resume replace the surface and ignore late callbacks from the released context', async () => {
  const spy = jest.spyOn(rendererModule, 'createGlobeRenderer');
  const first = globeTestContext(); const second = globeTestContext();
  const onError = jest.fn(); const onReady = jest.fn();
  await render(<GlobeSurface route={testRoute} mode="card" active reduceMotion onError={onError} onReady={onReady} />);
  const staleCreate = nativeCallback();
  await act(async () => { staleCreate(first.gl); });
  const staleFrameFailure = spy.mock.calls[0]![3]!;
  await act(async () => { appStateListener('background'); appStateListener('active'); });
  expect(first.context.deleteTexture).toHaveBeenCalledTimes(1);
  expect(nativeCallback()).not.toBe(staleCreate);
  await fireEvent(nativeView(), 'contextCreate', second.gl);
  await act(async () => { staleCreate(first.gl); staleFrameFailure(); });
  expect(spy).toHaveBeenCalledTimes(2);
  expect(onError).not.toHaveBeenCalled();
  expect(onReady).toHaveBeenCalledTimes(2);
  expect(second.context.deleteTexture).not.toHaveBeenCalled();
});

test('a hidden route releases its GPU resources and late native callbacks cannot recreate them', async () => {
  const { gl, context } = globeTestContext();
  const onError = jest.fn();
  const result = await render(<GlobeSurface route={testRoute} mode="card" active reduceMotion onError={onError} />);
  const staleCreate = nativeCallback();
  await act(async () => { staleCreate(gl); });
  await result.rerender(<GlobeSurface route={testRoute} mode="card" active={false} reduceMotion onError={onError} />);
  const allocations = context.createBuffer.mock.calls.length;
  await act(async () => { staleCreate(gl); });
  expect(context.createBuffer).toHaveBeenCalledTimes(allocations);
  expect(context.deleteTexture).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId('native-gl-view', { includeHiddenElements: true })).toBeNull();
  expect(onError).not.toHaveBeenCalled();
});

test('imperative camera failures stop the globe and further controls become harmless', async () => {
  const actual = rendererModule.createGlobeRenderer;
  jest.spyOn(rendererModule, 'createGlobeRenderer').mockImplementation((...args) => ({
    ...actual(...args), setCamera: () => { throw new Error('camera context lost'); },
  }));
  const onError = jest.fn(); const ref = createRef<GlobeSurfaceHandle>();
  await render(<GlobeSurface ref={ref} route={testRoute} mode="expanded" active reduceMotion onError={onError} />);
  await fireEvent(nativeView(), 'contextCreate', globeTestContext().gl);
  await act(async () => { ref.current?.zoomIn(); ref.current?.zoomOut(); ref.current?.resetView(); });
  expect(onError).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId('native-gl-view', { includeHiddenElements: true })).toBeNull();
});
