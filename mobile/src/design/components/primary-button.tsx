import { ActivityIndicator, Pressable, StyleSheet, Text, type PressableProps } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

type Props = PressableProps & {
  label: string;
  loading?: boolean;
  tone?: 'primary' | 'secondary' | 'danger';
};

export function PrimaryButton({ label, loading = false, tone = 'primary', disabled, ...props }: Props) {
  const isDisabled = disabled || loading;
  const contentColor = tone === 'danger' ? colors.white : tone === 'secondary' ? colors.greenDeep : colors.ink;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      style={({ pressed }) => [
        styles.button,
        tone === 'secondary' && styles.secondary,
        tone === 'danger' && styles.danger,
        (pressed || isDisabled) && styles.muted,
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
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 52,
    borderRadius: radii.pill,
    borderColor: colors.greenDeep,
    borderWidth: 1,
    backgroundColor: colors.green,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
  },
  secondary: { backgroundColor: colors.surfaceStrong, borderColor: colors.border, borderWidth: 1 },
  danger: { backgroundColor: colors.danger, borderColor: colors.danger },
  muted: { opacity: 0.58 },
  label: { color: colors.ink, fontSize: 16, fontWeight: '700' },
  secondaryLabel: { color: colors.greenDeep },
  dangerLabel: { color: colors.white },
});
