import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { AppState, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import type { JourneyRoute } from '../model/journey-route';
import { GlobeContext, type GlobeContextHandle } from './globe-context';

export type GlobeSurfaceHandle = {
  zoomIn(): void;
  zoomOut(): void;
  resetView(): void;
};

export type GlobeSurfaceProps = {
  route: JourneyRoute | null;
  mode: 'card' | 'expanded';
  active: boolean;
  /** Keep the native context while a covering transition temporarily hides it. */
  paused?: boolean;
  reduceMotion: boolean;
  style?: StyleProp<ViewStyle>;
  onReady?: () => void;
  onError?: () => void;
  onRelease?: () => void;
  onLoading?: () => void;
};

/** Native view-owned contexts must not outlive the visible, foreground globe. */
export const GlobeSurface = forwardRef<GlobeSurfaceHandle, GlobeSurfaceProps>(function GlobeSurface(
  props, ref,
) {
  const context = useRef<GlobeContextHandle>(null);
  const [lifecycle, setLifecycle] = useState(() => ({
    foreground: AppState.currentState === 'active', generation: 0,
  }));

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      const foreground = state === 'active';
      // Stop synchronously, before a queued route update can reach a destroyed
      // native surface. A new key also handles background/resume events batched
      // into one React commit; the old context is never reused.
      if (!foreground) context.current?.release();
      setLifecycle((previous) => ({
        foreground, generation: previous.generation + (foreground ? 0 : 1),
      }));
    });
    return () => subscription.remove();
  }, []);

  useImperativeHandle(ref, () => ({
    zoomIn: () => context.current?.zoomIn(),
    zoomOut: () => context.current?.zoomOut(),
    resetView: () => context.current?.resetView(),
  }), []);

  return props.active && lifecycle.foreground
    ? <GlobeContext key={`${props.mode}:${lifecycle.generation}`} ref={context} {...props} />
    : <View accessible={false} style={[styles.surface, props.style]} />;
});

const styles = StyleSheet.create({ surface: { overflow: 'hidden', backgroundColor: 'transparent' } });
