import { useEffect, useState } from 'react';
import { Animated, type StyleProp, type ViewStyle } from 'react-native';

import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';

export function AmbientHeroGlow({ color, style }: { color: string; style: StyleProp<ViewStyle> }) {
  const reduceMotion = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    if (reduceMotion) {
      progress.setValue(0);
      return;
    }
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(progress, { toValue: 1, duration: 4200, useNativeDriver: true }),
        Animated.timing(progress, { toValue: 0, duration: 4200, useNativeDriver: true }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [progress, reduceMotion]);

  return (
    <Animated.View
      pointerEvents="none"
      style={[
        style,
        {
          backgroundColor: color,
          opacity: progress.interpolate({ inputRange: [0, 1], outputRange: [0.12, 0.21] }),
          transform: [
            { translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [0, -10] }) },
            { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [0, 8] }) },
            { scale: progress.interpolate({ inputRange: [0, 1], outputRange: [1, 1.06] }) },
          ],
        },
      ]}
    />
  );
}
