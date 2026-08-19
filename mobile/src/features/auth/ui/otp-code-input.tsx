import { useCallback, useMemo, useRef } from 'react';
import {
  StyleSheet,
  Text,
  TextInput,
  View,
  type NativeSyntheticEvent,
  type TextInputKeyPressEventData,
} from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

const OTP_LENGTH = 6;

export function OtpCodeInput({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const inputs = useRef<(TextInput | null)[]>([]);
  const digits = useMemo(
    () => Array.from({ length: OTP_LENGTH }, (_, index) => value[index] ?? ''),
    [value],
  );

  const updateAt = useCallback((index: number, input: string) => {
    const incoming = input.replace(/\D/g, '');
    if (!incoming) {
      const next = [...digits];
      next[index] = '';
      onChange(next.join(''));
      return;
    }
    const next = [...digits];
    for (let offset = 0; offset < incoming.length && index + offset < OTP_LENGTH; offset += 1) {
      next[index + offset] = incoming[offset] ?? '';
    }
    onChange(next.join('').slice(0, OTP_LENGTH));
    inputs.current[Math.min(index + incoming.length, OTP_LENGTH - 1)]?.focus();
  }, [digits, onChange]);

  const handleKeyPress = useCallback((
    index: number,
    event: NativeSyntheticEvent<TextInputKeyPressEventData>,
  ) => {
    if (event.nativeEvent.key !== 'Backspace' || digits[index]) return;
    const previousIndex = Math.max(0, index - 1);
    const next = [...digits];
    next[previousIndex] = '';
    onChange(next.join(''));
    inputs.current[previousIndex]?.focus();
  }, [digits, onChange]);

  return (
    <View style={styles.group}>
      <Text style={styles.label}>Verification code</Text>
      <View accessibilityLabel="Six digit verification code" style={styles.row}>
        {digits.map((digit, index) => {
          const active = value.length === index || (value.length === OTP_LENGTH && index === OTP_LENGTH - 1);
          return (
            <TextInput
              key={index}
              testID={`passenger-otp-digit-${index + 1}`}
              ref={(node) => { inputs.current[index] = node; }}
              accessibilityLabel={`Verification code digit ${index + 1}`}
              autoFocus={index === 0}
              editable={!disabled}
              keyboardType="number-pad"
              textContentType={index === 0 ? 'oneTimeCode' : 'none'}
              autoComplete={index === 0 ? 'sms-otp' : 'off'}
              maxLength={index === 0 ? OTP_LENGTH : 1}
              selectTextOnFocus
              value={digit}
              onChangeText={(next) => updateAt(index, next)}
              onKeyPress={(event) => handleKeyPress(index, event)}
              style={[styles.box, active && styles.activeBox, digit && styles.filledBox]}
            />
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  label: { color: colors.ink, fontSize: 14, fontWeight: '700' },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm },
  box: {
    flex: 1,
    minWidth: 42,
    maxWidth: 54,
    height: 58,
    borderWidth: 1,
    borderColor: 'rgba(23,109,148,0.25)',
    borderRadius: radii.md,
    backgroundColor: colors.surfaceStrong,
    color: colors.ink,
    fontSize: 23,
    fontWeight: '900',
    textAlign: 'center',
    shadowColor: colors.blueDeep,
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 1,
  },
  activeBox: { borderColor: colors.blue, borderWidth: 2, backgroundColor: '#F6FCFF' },
  filledBox: { color: colors.blueDeep },
});
