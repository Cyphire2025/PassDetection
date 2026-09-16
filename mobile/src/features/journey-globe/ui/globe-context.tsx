import { GLView, type ExpoWebGLRenderingContext } from 'expo-gl';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';

import { createGlobeRenderer, type GlobeRenderer } from '../render/globe-renderer';
import { loadLandMask } from '../render/land-asset';
import type { GlobeSurfaceHandle, GlobeSurfaceProps } from './globe-surface';

export type GlobeContextHandle = GlobeSurfaceHandle & { release(): void };

/** A failure in optional GPU rendering cannot interrupt the trip's other content. */
export const GlobeContext = forwardRef<GlobeContextHandle, GlobeSurfaceProps>(function GlobeContext(
  { route, mode, reduceMotion, style, onReady, onError }, ref,
) {
  const renderer = useRef<GlobeRenderer | null>(null);
  const alive = useRef(true);
  const generation = useRef(0);
  const errorReported = useRef(false);
  const [failed, setFailed] = useState(false);
  const pinchStart = useRef(1);
  const latest = useRef({ route, reduceMotion, onReady, onError });
  useLayoutEffect(() => { latest.current = { route, reduceMotion, onReady, onError }; },
    [route, reduceMotion, onReady, onError]);

  const disposeRenderer = useCallback(() => {
    generation.current += 1;
    const previous = renderer.current;
    renderer.current = null;
    // Expo may already have destroyed its native context. Cleanup must not
    // replace a usable fallback with a second error from that dead context.
    try { previous?.dispose(); } catch { /* Native GLView teardown owns final context cleanup. */ }
  }, []);
  const release = useCallback(() => {
    alive.current = false;
    disposeRenderer();
  }, [disposeRenderer]);
  useLayoutEffect(() => {
    alive.current = true;
    return release;
  }, [release]);

  const fail = useCallback(() => {
    if (!alive.current || errorReported.current) return;
    errorReported.current = true;
    disposeRenderer();
    setFailed(true);
    latest.current.onError?.();
  }, [disposeRenderer]);
  const update = useCallback((operation: (view: GlobeRenderer) => void) => {
    const view = renderer.current;
    if (!alive.current || !view) return;
    try { operation(view); } catch { fail(); }
  }, [fail]);

  // Route lookup and synchronization can change after initial GL setup. These
  // updates allocate GPU buffers too, and need the same fallback as first load.
  useEffect(() => { update((view) => view.setRoute(route)); }, [route, update]);
  useEffect(() => { update((view) => view.setReducedMotion(reduceMotion)); }, [reduceMotion, update]);
  useImperativeHandle(ref, () => ({
    release,
    zoomIn: () => update((view) => { const camera = view.getCamera(); view.setCamera({ ...camera, zoom: camera.zoom * 1.25 }); }),
    zoomOut: () => update((view) => { const camera = view.getCamera(); view.setCamera({ ...camera, zoom: camera.zoom / 1.25 }); }),
    resetView: () => update((view) => view.resetView()),
  }), [release, update]);

  const createContext = useCallback((gl: ExpoWebGLRenderingContext) => {
    if (!alive.current || errorReported.current) return;
    disposeRenderer();
    const contextGeneration = generation.current;
    try {
      const view = createGlobeRenderer(gl, loadLandMask(), mode, () => {
        if (generation.current === contextGeneration) fail();
      });
      renderer.current = view;
      view.setRoute(latest.current.route);
      view.setReducedMotion(latest.current.reduceMotion);
      view.renderStill();
      view.setActive(true);
    } catch { fail(); return; }
    if (alive.current && generation.current === contextGeneration) latest.current.onReady?.();
  }, [disposeRenderer, fail, mode]);

  const gestures = useMemo(() => {
    const pan = Gesture.Pan().enabled(mode === 'expanded').minDistance(3).maxPointers(1).runOnJS(true)
      .onChange((event) => update((view) => {
        const camera = view.getCamera();
        view.setCamera({ ...camera, longitude: camera.longitude - event.changeX * 0.006 / camera.zoom,
          latitude: camera.latitude + event.changeY * 0.006 / camera.zoom });
      }));
    const pinch = Gesture.Pinch().enabled(mode === 'expanded').runOnJS(true)
      .onBegin(() => update((view) => { pinchStart.current = view.getCamera().zoom; }))
      .onUpdate((event) => update((view) => view.setCamera({ ...view.getCamera(), zoom: pinchStart.current * event.scale })));
    return Gesture.Simultaneous(pan, pinch);
  }, [mode, update]);

  return (
    <GestureDetector gesture={gestures}>
      <View accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
        pointerEvents={mode === 'card' ? 'none' : 'auto'} style={[styles.surface, style]}>
        {!failed ? <GLView style={StyleSheet.absoluteFill} onContextCreate={createContext} msaaSamples={4} /> : null}
      </View>
    </GestureDetector>
  );
});

const styles = StyleSheet.create({ surface: { overflow: 'hidden', backgroundColor: 'transparent' } });
