import ScanLine from 'lucide-react-native/icons/scan-line';
import { StyleSheet, Text } from 'react-native';

import { GlassCard } from '@/design/components/glass-card';
import { colors, spacing } from '@/design/theme';
import type { EventReadinessCaptureGate } from '@/features/coordinator/data/event-readiness';

type Props = Readonly<{
  gate: EventReadinessCaptureGate;
}>;

export function AttendanceScannerLock({ gate }: Props) {
  const loading = gate === 'loading';
  return (
    <GlassCard testID="attendance-camera-locked" style={styles.card}>
      <ScanLine color={colors.danger} size={30} />
      <Text accessibilityRole="alert" style={styles.title}>
        {loading ? 'Scanner checks in progress' : 'Scanner locked by Event Ready'}
      </Text>
      <Text style={styles.message}>
        {loading
          ? 'Wait for every required readiness check to finish before scanning.'
          : 'Resolve every BLOCK item above, then tap Refresh readiness.'}
      </Text>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, alignItems: 'center', borderColor: colors.danger },
  title: { color: colors.danger, fontSize: 18, fontWeight: '900', textAlign: 'center' },
  message: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center' },
});
