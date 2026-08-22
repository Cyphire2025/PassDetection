import { useRouter, type Href } from 'expo-router';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import TriangleAlert from 'lucide-react-native/icons/triangle-alert';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useRouteFocus } from '@/core/query/use-route-focus';
import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';
import { attendanceQueueCounts } from '@/features/coordinator/data/attendance-queue';

type Props = Readonly<{ tripId: string | null }>;

// Expo refreshes its ignored typed-route union during native builds. Keep the
// source route typed while this newly added file precedes that generated step.
const SCAN_ISSUES_ROUTE = '/(coordinator)/operations/scan-issues' as Href;

function safeIssueCount(counts: Record<string, number>): number {
  const needsReview = counts.needs_review ?? 0;
  const rejected = counts.rejected ?? 0;
  if (!Number.isSafeInteger(needsReview) || !Number.isSafeInteger(rejected)) return 0;
  return Math.max(0, needsReview) + Math.max(0, rejected);
}

export function AttendanceIssuesBanner({ tripId }: Props) {
  const router = useRouter();
  const focused = useRouteFocus();
  const loadVersion = useRef(0);
  const [loaded, setLoaded] = useState<Readonly<{
    count: number | null;
    tripId: string;
  }> | null>(null);

  useEffect(() => {
    const version = loadVersion.current + 1;
    loadVersion.current = version;
    if (!focused || !tripId) return;
    void attendanceQueueCounts(tripId)
      .then((counts) => {
        if (loadVersion.current === version) {
          setLoaded({ count: safeIssueCount(counts), tripId });
        }
      })
      .catch(() => {
        if (loadVersion.current === version) setLoaded({ count: null, tripId });
      });
    return () => {
      loadVersion.current += 1;
    };
  }, [focused, tripId]);
  const count = focused && tripId && loaded?.tripId === tripId ? loaded.count : null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={count === null ? 'Open Scan Issues' : `Open Scan Issues, ${count} unresolved`}
      onPress={() => router.push(SCAN_ISSUES_ROUTE)}
      style={({ pressed }) => pressed && styles.pressed}>
      <GlassCard style={[styles.card, count !== 0 && styles.attention]}>
        <TriangleAlert color={count === 0 ? colors.greenDeep : colors.warning} size={22} />
        <View style={styles.copy}>
          <Text style={styles.title}>Scan Issues</Text>
          <Text style={styles.subtitle}>
            {count === null
              ? 'Open the persistent review center.'
              : count === 0
                ? 'No unresolved or terminal scan records.'
                : `${count} scan record${count === 1 ? '' : 's'} require review or acknowledgement.`}
          </Text>
        </View>
        <ChevronRight color={colors.inkMuted} size={20} />
      </GlassCard>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radii.md,
  },
  attention: { borderColor: colors.warning, borderWidth: 1 },
  copy: { flex: 1, gap: 2 },
  title: { color: colors.ink, fontSize: 14, fontWeight: '900' },
  subtitle: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  pressed: { opacity: 0.68 },
});
