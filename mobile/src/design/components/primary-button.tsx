import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  Pressable,
  StyleSheet,
  Text,
  type GestureResponderEvent,
  type PressableProps,
} from 'react-native';

import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { colors, radii, spacing } from '@/design/theme';

type Props = PressableProps & {
  label: string;
  loading?: boolean;
  tone?: 'primary' | 'secondary' | 'danger';
};

export function PrimaryButton({
  label,
  loading = false,
  tone = 'primary',
  disabled,
  onPressIn,
  onPressOut,
  accessibilityLabel,
  accessibilityState,
  style,
  ...props
}: Props) {
  const isDisabled = disabled || loading;
  const contentColor = tone === 'danger' ? colors.white : tone === 'secondary' ? colors.greenDeep : colors.ink;
  const reduceMotion = useReducedMotion();
  const [scale] = useState(() => new Animated.Value(1));
  const [shadowOpacity] = useState(() => new Animated.Value(0.16));

  const animatePress = useCallback((pressed: boolean) => {
    if (reduceMotion || isDisabled) return;
    Animated.parallel([
      Animated.spring(scale, {
        toValue: pressed ? 0.98 : 1,
        damping: pressed ? 22 : 15,
        stiffness: pressed ? 360 : 250,
        mass: 0.65,
        useNativeDriver: false,
      }),
      Animated.timing(shadowOpacity, {
        toValue: pressed ? 0.07 : 0.16,
        duration: pressed ? 90 : 190,
        useNativeDriver: false,
      }),
    ]).start();
  }, [isDisabled, reduceMotion, scale, shadowOpacity]);

  const handlePressIn = useCallback((event: GestureResponderEvent) => {
    animatePress(true);
    onPressIn?.(event);
  }, [animatePress, onPressIn]);

  const handlePressOut = useCallback((event: GestureResponderEvent) => {
    animatePress(false);
    onPressOut?.(event);
  }, [animatePress, onPressOut]);

  return (
    <Animated.View style={[styles.shadow, { shadowOpacity, transform: [{ scale }] }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel ?? label}
        accessibilityState={{ ...accessibilityState, disabled: isDisabled, busy: loading }}
        disabled={isDisabled}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        style={(state) => [
          styles.button,
          tone === 'secondary' && styles.secondary,
          tone === 'danger' && styles.danger,
          state.pressed && styles.pressed,
          isDisabled && styles.muted,
          typeof style === 'function' ? style(state) : style,
        ]}
        {...props}>
        {loading ? (
          <ActivityIndicator color={contentColor} />
        ) : (
          <Text
            style={[
              styles.label,
              tone === 'secondary' && styles.secondaryLabel,
              tone === 'danger' && styles.dangerLabel,
            ]}>
            {label}
          </Text>
        )}
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  shadow: {
    borderRadius: radii.pill,
    shadowColor: colors.greenDeep,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  button: {
    minHeight: 54,
    borderRadius: radii.pill,
    borderColor: colors.green,
    borderWidth: 1,
    backgroundColor: colors.green,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
  },
  secondary: { backgroundColor: colors.white, borderColor: colors.blue, borderWidth: 1, shadowOpacity: 0.08 },
  danger: { backgroundColor: colors.danger, borderColor: colors.danger },
  pressed: { opacity: 0.94 },
  muted: { opacity: 0.58 },
  label: {
    flexShrink: 1,
    color: colors.navy,
    fontSize: 16,
    lineHeight: 21,
    fontWeight: '900',
    paddingVertical: spacing.sm,
    textAlign: 'center',
  },
  secondaryLabel: { color: colors.blueDeep },
  dangerLabel: { color: colors.white },
});
