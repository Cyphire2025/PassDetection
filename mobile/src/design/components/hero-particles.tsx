import { useEffect, useState } from 'react';
import { Animated, Easing, StyleSheet } from 'react-native';

import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { colors } from '@/design/theme';

export function HeroParticles() {
  const reduceMotion = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    if (reduceMotion) {
      progress.setValue(0.35);
      return;
    }
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(progress, {
          toValue: 1,
          duration: 5200,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
        Animated.timing(progress, {
          toValue: 0,
          duration: 5200,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [progress, reduceMotion]);

  return (
    <Animated.View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Animated.View
        style={[
          styles.circle,
          styles.one,
          { transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [0, 13] }) }] },
        ]}
      />
      <Animated.View
        style={[
          styles.circle,
          styles.two,
          { transform: [{ translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [0, -16] }) }] },
        ]}
      />
      <Animated.View
        style={[
          styles.circle,
          styles.three,
          { transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [10, -8] }) }] },
        ]}
      />
      <Animated.View
        style={[
          styles.circle,
          styles.four,
          {
            transform: [
              { translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [-5, 9] }) },
              { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [6, -10] }) },
            ],
          },
        ]}
      />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  circle: { position: 'absolute', borderRadius: 999, backgroundColor: colors.white, opacity: 0.18 },
  one: { width: 10, height: 10, left: '62%', top: 24 },
  two: { width: 7, height: 7, right: 42, top: '54%', backgroundColor: colors.aqua, opacity: 0.28 },
  three: { width: 14, height: 14, left: '78%', bottom: 22, opacity: 0.11 },
  four: { width: 6, height: 6, left: '47%', top: '44%', backgroundColor: colors.aqua, opacity: 0.25 },
});
