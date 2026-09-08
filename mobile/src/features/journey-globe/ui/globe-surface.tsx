import { GLView, type ExpoWebGLRenderingContext } from 'expo-gl';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { AppState, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';

import type { JourneyRoute } from '../model/journey-route';
import { createGlobeRenderer, type GlobeRenderer } from '../render/globe-renderer';
import { loadLandMask } from '../render/land-asset';

export type GlobeSurfaceHandle = {
  zoomIn(): void;
  zoomOut(): void;
  resetView(): void;
};

export type GlobeSurfaceProps = {
  route: JourneyRoute | null;
  mode: 'card' | 'expanded';
  active: boolean;
  reduceMotion: boolean;
  style?: StyleProp<ViewStyle>;
  onReady?: () => void;
  onError?: () => void;
};

/** A fully offline GPU Earth. Only expanded mode owns touch gestures. */
export const GlobeSurface = forwardRef<GlobeSurfaceHandle, GlobeSurfaceProps>(function GlobeSurface(
  { route, mode, active, reduceMotion, style, onReady, onError }, ref,
) {
  const renderer = useRef<GlobeRenderer | null>(null);
  const mounted = useRef(true);
  const generation = useRef(0);
  const appActive = useRef(AppState.currentState === 'active');
  const pinchStart = useRef(1);
  const latest = useRef({ route, active, reduceMotion, onReady, onError });
  useEffect(() => { latest.current = { route, active, reduceMotion, onReady, onError }; },
    [route, active, reduceMotion, onReady, onError]);

  useEffect(() => {
    mounted.current = true;
    const subscription = AppState.addEventListener('change', (state) => {
      appActive.current = state === 'active';
      renderer.current?.setActive(latest.current.active && appActive.current);
    });
    return () => {
      mounted.current = false;
      generation.current += 1;
      subscription.remove();
      renderer.current?.dispose();
      renderer.current = null;
    };
  }, []);

  useEffect(() => { renderer.current?.setRoute(route); }, [route]);
  useEffect(() => { renderer.current?.setActive(active && appActive.current); }, [active]);
  useEffect(() => { renderer.current?.setReducedMotion(reduceMotion); }, [reduceMotion]);

  useImperativeHandle(ref, () => ({
    zoomIn() {
      const view = renderer.current;
      if (view) { const camera = view.getCamera(); view.setCamera({ ...camera, zoom: camera.zoom * 1.25 }); }
    },
    zoomOut() {
      const view = renderer.current;
      if (view) { const camera = view.getCamera(); view.setCamera({ ...camera, zoom: camera.zoom / 1.25 }); }
    },
    resetView() { renderer.current?.resetView(); },
  }), []);

  const createContext = useCallback((gl: ExpoWebGLRenderingContext) => {
    const contextGeneration = ++generation.current;
    renderer.current?.dispose();
    renderer.current = null;
    try {
      const land = loadLandMask();
      if (!mounted.current || generation.current !== contextGeneration) return;
      const view = createGlobeRenderer(gl, land, mode, () => {
        if (mounted.current && generation.current === contextGeneration) latest.current.onError?.();
      });
      renderer.current = view;
      view.setRoute(latest.current.route);
      view.setReducedMotion(latest.current.reduceMotion);
      view.renderStill();
      view.setActive(latest.current.active && appActive.current);
      latest.current.onReady?.();
    } catch {
      if (!mounted.current || generation.current !== contextGeneration) return;
      renderer.current?.dispose();
      renderer.current = null;
      latest.current.onError?.();
    }
  }, [mode]);

  const gestures = useMemo(() => {
    const pan = Gesture.Pan().enabled(mode === 'expanded').minDistance(3).maxPointers(1).runOnJS(true)
      .onChange((event) => {
        const view = renderer.current;
        if (!view) return;
        const camera = view.getCamera();
        view.setCamera({ ...camera, longitude: camera.longitude - event.changeX * 0.006 / camera.zoom,
          latitude: camera.latitude + event.changeY * 0.006 / camera.zoom });
      });
    const pinch = Gesture.Pinch().enabled(mode === 'expanded').runOnJS(true)
      .onBegin(() => { pinchStart.current = renderer.current?.getCamera().zoom ?? 1; })
      .onUpdate((event) => {
        const view = renderer.current;
        if (view) view.setCamera({ ...view.getCamera(), zoom: pinchStart.current * event.scale });
      });
    return Gesture.Simultaneous(pan, pinch);
  }, [mode]);

  return (
    <GestureDetector gesture={gestures}>
      <View
        accessible={false}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        pointerEvents={mode === 'card' ? 'none' : 'auto'}
        style={[styles.surface, style]}>
        <GLView key={mode} style={StyleSheet.absoluteFill} onContextCreate={createContext} msaaSamples={4} />
      </View>
    </GestureDetector>
  );
});

const styles = StyleSheet.create({ surface: { overflow: 'hidden', backgroundColor: 'transparent' } });
