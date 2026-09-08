import { createContext, useCallback, useContext, useEffect, useRef, type PropsWithChildren } from 'react';
import { Animated, Image, StyleSheet, View } from 'react-native';

import { fitLaunchLogo, type LaunchRect } from './launch-geometry';

const logo = require('../../../assets/images/global-connect-launch-logo-alpha.png') as number;
const finalLogoFrame = fitLaunchLogo(142, 48);

export const LaunchChoreographyContext = createContext<{
  active: boolean;
  progress: Animated.Value;
  registerLogo: (bounds: LaunchRect | null) => void;
} | null>(null);

/** A stationary measured destination; only its artwork is hidden during launch. */
export function LaunchLogoAnchor() {
  const choreography = useContext(LaunchChoreographyContext);
  const registerLogo = choreography?.registerLogo;
  const slot = useRef<View>(null);
  const measure = useCallback(() => {
    slot.current?.measureInWindow((x, y, width, height) => {
      if (width > 0 && height > 0 && [x, y, width, height].every(Number.isFinite)) {
        registerLogo?.({ x, y, width, height });
      }
    });
  }, [registerLogo]);
  useEffect(() => {
    // Router presentation may finish just after layout; remeasure on its next frame.
    const frame = requestAnimationFrame(measure);
    return () => { cancelAnimationFrame(frame); registerLogo?.(null); };
  }, [measure, registerLogo]);
  return (
    <View ref={slot} testID="launch-logo-anchor" collapsable={false} onLayout={measure} style={styles.logoSlot}
      accessibilityRole="image" accessibilityLabel="Global Connect Travels">
      <Image source={logo} resizeMode="contain" style={[styles.logo, finalLogoFrame, choreography?.active && styles.hidden]} />
    </View>
  );
}

/** Stagger the welcome content without moving the measured logo destination. */
export function LaunchEntrance({ children, order }: PropsWithChildren<{ order: 0 | 1 }>) {
  const choreography = useContext(LaunchChoreographyContext);
  const progress = choreography?.active ? choreography.progress : null;
  const start = order === 0 ? 0.32 : 0.46;
  const end = order === 0 ? 0.87 : 1;
  return (
    <Animated.View testID={`launch-entrance-${order}`}
      needsOffscreenAlphaCompositing={Boolean(progress)}
      renderToHardwareTextureAndroid={Boolean(progress)}
      style={progress ? {
      opacity: progress.interpolate({ inputRange: [0, start, end], outputRange: [0, 0, 1], extrapolate: 'clamp' }),
      transform: [{ translateY: progress.interpolate({ inputRange: [0, start, end], outputRange: [96, 96, 0], extrapolate: 'clamp' }) }],
    } : undefined}>
      {children}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  logoSlot: { width: 142, height: 48, overflow: 'hidden' },
  logo: { position: 'absolute' },
  hidden: { opacity: 0 },
});
