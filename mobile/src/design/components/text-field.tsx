import Eye from 'lucide-react-native/icons/eye';
import EyeOff from 'lucide-react-native/icons/eye-off';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

type Props = TextInputProps & {
  label: string;
  error?: string | null;
  showPasswordToggle?: boolean;
};

export function TextField({ label, error, showPasswordToggle = false, secureTextEntry, style, ...props }: Props) {
  const [passwordVisible, setPasswordVisible] = useState(false);
  const canTogglePassword = showPasswordToggle && secureTextEntry;
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.inputFrame, error ? styles.errorInput : null]}>
        <TextInput
          accessibilityLabel={label}
          placeholderTextColor={colors.inkMuted}
          secureTextEntry={Boolean(secureTextEntry && !passwordVisible)}
          style={[styles.input, style]}
          {...props}
        />
        {canTogglePassword ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={passwordVisible ? 'Hide password' : 'Show password'}
            hitSlop={8}
            onPress={() => setPasswordVisible((visible) => !visible)}
            style={({ pressed }) => [styles.eyeButton, pressed && styles.eyePressed]}>
            {passwordVisible
              ? <EyeOff color={colors.blueDeep} size={21} />
              : <Eye color={colors.blueDeep} size={21} />}
          </Pressable>
        ) : null}
      </View>
      {error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  label: { color: colors.ink, fontSize: 14, fontWeight: '700' },
  inputFrame: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(23,109,148,0.28)',
    borderRadius: radii.md,
    backgroundColor: colors.surfaceStrong,
    shadowColor: colors.blueDeep,
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 1,
  },
  input: {
    minHeight: 50,
    flex: 1,
    color: colors.ink,
    fontSize: 16,
    paddingHorizontal: spacing.lg,
  },
  eyeButton: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  eyePressed: { opacity: 0.58, transform: [{ scale: 0.96 }] },
  errorInput: { borderColor: colors.danger },
  error: { color: colors.danger, fontSize: 13 },
});
