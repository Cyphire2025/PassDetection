import type { BarcodeScanningResult } from 'expo-camera';
import { useCallback, useState } from 'react';
import { StyleSheet, Text, TextInput } from 'react-native';

import { env } from '@/core/config/env';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';

type Props = Readonly<{
  captureAllowed: boolean;
  onScan: (result: BarcodeScanningResult) => Promise<void>;
}>;

function syntheticBarcodeResult(data: string): BarcodeScanningResult {
  return {
    bounds: {
      origin: { x: 0, y: 0 },
      size: { height: 0, width: 0 },
    },
    cornerPoints: [],
    data,
    raw: data,
    type: 'qr',
  };
}

export function AttendanceE2eFixtureInput({ captureAllowed, onScan }: Props) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (!captureAllowed || busy || !value) return;
    const protectedValue = value;
    setBusy(true);
    setError(null);
    setValue('');
    try {
      await onScan(syntheticBarcodeResult(protectedValue));
    } catch {
      setError('The synthetic scan could not be submitted.');
    } finally {
      setBusy(false);
    }
  }, [busy, captureAllowed, onScan, value]);

  if (!env.maestroAttendanceFixtureEnabled) return null;

  return (
    <GlassCard style={styles.card} testID="attendance-e2e-fixture">
      <Text style={styles.title}>Preview acceptance fixture</Text>
      <Text style={styles.message}>
        Protected synthetic input follows the same secure queue and confirmation path as the camera.
      </Text>
      <Text style={styles.label}>Synthetic attendance QR</Text>
      <TextInput
        testID="attendance-e2e-qr-input"
        accessibilityLabel="Synthetic attendance QR"
        value={value}
        onChangeText={setValue}
        autoCapitalize="none"
        autoComplete="off"
        autoCorrect={false}
        editable={!busy}
        maxLength={49}
        returnKeyType="done"
        secureTextEntry
        placeholder="Protected fixture value"
        placeholderTextColor={colors.inkMuted}
        style={styles.input}
        onSubmitEditing={() => void submit()}
      />
      {error ? (
        <Text accessibilityLiveRegion="polite" accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}
      <PrimaryButton
        testID="attendance-e2e-submit"
        label="Submit synthetic QR"
        disabled={!captureAllowed || !value}
        loading={busy}
        onPress={() => void submit()}
      />
      {!captureAllowed ? (
        <Text accessibilityLiveRegion="polite" style={styles.blocked}>
          Allow camera access before synthetic input is enabled.
        </Text>
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, borderColor: colors.warning, borderWidth: 1 },
  title: { color: colors.ink, fontSize: 15, fontWeight: '900' },
  message: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
  label: { color: colors.ink, fontSize: 13, fontWeight: '700' },
  input: {
    minHeight: 50,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    backgroundColor: colors.surfaceStrong,
    color: colors.ink,
    fontSize: 16,
    paddingHorizontal: spacing.md,
  },
  error: { color: colors.danger, fontSize: 12 },
  blocked: { color: colors.warning, fontSize: 12, fontWeight: '700' },
});
