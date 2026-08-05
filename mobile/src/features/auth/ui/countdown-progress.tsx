import { useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, View } from 'react-native';

import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { colors, radii, spacing } from '@/design/theme';

export function CountdownProgress({ remaining, total }: { remaining: number; total: number }) {
  const reduceMotion = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(total > 0 ? remaining / total : 0));
  const animation = useRef<Animated.CompositeAnimation | null>(null);
  const previousRemaining = useRef<number | null>(null);
  const previousTotal = useRef(total);
  const fraction = total > 0 ? Math.min(1, Math.max(0, remaining / total)) : 0;

  useEffect(() => {
    if (reduceMotion) {
      animation.current?.stop();
      progress.setValue(fraction);
      previousRemaining.current = remaining;
      previousTotal.current = total;
      return;
    }

    const countdownRestarted =
      previousRemaining.current === null ||
      remaining > previousRemaining.current ||
      total !== previousTotal.current;

    previousRemaining.current = remaining;
    previousTotal.current = total;

    if (!countdownRestarted) return;

    animation.current?.stop();
    progress.setValue(fraction);
    animation.current = Animated.timing(progress, {
      toValue: 0,
      duration: Math.max(0, remaining * 1000),
      easing: Easing.linear,
      useNativeDriver: false,
    });
    animation.current.start();
  }, [fraction, progress, reduceMotion, remaining, total]);

  useEffect(() => () => animation.current?.stop(), []);

  return (
    <View accessibilityRole="timer" accessibilityLabel={`${remaining} seconds until another code can be sent`} style={styles.root}>
      <View style={styles.copy}>
        <Text style={styles.label}>Resend unlocks automatically</Text>
        <Text style={styles.time}>{remaining}s</Text>
      </View>
      <View style={styles.track}>
        <Animated.View
          style={[
            styles.fill,
            { width: progress.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { gap: spacing.sm },
  copy: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  label: { flex: 1, color: colors.inkMuted, fontSize: 12, fontWeight: '700' },
  time: { color: colors.blueDeep, fontSize: 13, fontWeight: '900', fontVariant: ['tabular-nums'] },
  track: { height: 5, overflow: 'hidden', borderRadius: radii.pill, backgroundColor: colors.blueSoft },
  fill: { height: '100%', borderRadius: radii.pill, backgroundColor: colors.aqua },
});
