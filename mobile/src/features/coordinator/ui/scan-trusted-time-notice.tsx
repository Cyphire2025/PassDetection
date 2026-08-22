import ClockAlert from 'lucide-react-native/icons/clock-alert';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';
import {
  trustedAttendanceScanTime,
  trustedScanClockDriftNotice,
} from '@/features/coordinator/data/trusted-scan-time';
import { attendanceScanErrorFeedback } from '@/features/coordinator/data/attendance-scan-error';

type Props = Readonly<{
  blockingNotice: string | null;
  refreshSignal: string;
}>;

export function ScanTrustedTimeNotice({ blockingNotice, refreshSignal }: Props) {
  const [probeNotice, setProbeNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    trustedAttendanceScanTime().then((time) => {
      if (active) setProbeNotice(trustedScanClockDriftNotice(time.deviceClockDifferenceMs));
    }).catch((error: unknown) => {
      if (active) setProbeNotice(attendanceScanErrorFeedback(error).message);
    });
    return () => {
      active = false;
    };
  }, [refreshSignal]);

  const notice = blockingNotice ?? probeNotice;
  if (!notice) return null;
  return (
    <View accessibilityRole="alert" style={styles.notice}>
      <ClockAlert color={colors.danger} size={22} />
      <View style={styles.copy}>
        <Text style={styles.title}>Verified event time warning</Text>
        <Text style={styles.message}>{notice}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  notice: {
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.danger,
    backgroundColor: colors.surface,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    padding: spacing.md,
  },
  copy: { flex: 1, gap: spacing.xs },
  title: { color: colors.danger, fontSize: 14, fontWeight: '900' },
  message: { color: colors.ink, fontSize: 13, lineHeight: 19, fontWeight: '700' },
});
