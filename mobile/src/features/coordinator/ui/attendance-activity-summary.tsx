import ChevronDown from 'lucide-react-native/icons/chevron-down';
import ChevronUp from 'lucide-react-native/icons/chevron-up';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';
import type { AttendanceSession } from '@/features/coordinator/api/coordinator-contracts';

export type ExpandedAttendanceRoster = 'counted' | 'missing' | null;

export function AttendanceActivitySummary({
  session,
  expanded,
  onToggle,
}: {
  session: AttendanceSession;
  expanded: ExpandedAttendanceRoster;
  onToggle: (status: Exclude<ExpandedAttendanceRoster, null>) => void;
}) {
  const assigned = Math.max(0, session.assigned_count);
  const counted = Math.min(Math.max(0, session.scanned_count), assigned);
  const missing = Math.max(0, assigned - counted);
  const progress = assigned > 0 ? counted / assigned : 0;

  return (
    <GlassCard style={styles.card}>
      <View style={styles.heading}>
        <View style={styles.headingText}>
          <Text accessibilityRole="header" style={styles.title}>{session.name}</Text>
          <Text style={styles.subtitle}>{counted} of {assigned} counted</Text>
        </View>
        <Text style={styles.percent}>{Math.round(progress * 100)}%</Text>
      </View>
      <View
        accessibilityLabel={`${Math.round(progress * 100)} percent attendance complete`}
        accessibilityRole="progressbar"
        accessibilityValue={{ min: 0, max: assigned, now: counted }}
        style={styles.track}>
        <View style={[styles.progress, { width: `${progress * 100}%` }]} />
      </View>
      <RosterToggle
        label="Counted"
        count={counted}
        expanded={expanded === 'counted'}
        onPress={() => onToggle('counted')}
      />
      <RosterToggle
        label="Missing"
        count={missing}
        expanded={expanded === 'missing'}
        onPress={() => onToggle('missing')}
      />
    </GlassCard>
  );
}

function RosterToggle({
  label,
  count,
  expanded,
  onPress,
}: {
  label: string;
  count: number;
  expanded: boolean;
  onPress: () => void;
}) {
  const Chevron = expanded ? ChevronUp : ChevronDown;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded }}
      accessibilityLabel={`${label}, ${count} passengers`}
      onPress={onPress}
      style={({ pressed }) => [styles.toggle, pressed && styles.pressed]}>
      <View style={styles.toggleText}>
        <Text style={styles.toggleLabel}>{label}</Text>
        <Text style={styles.toggleCount}>{count.toLocaleString()}</Text>
      </View>
      <Chevron color={colors.inkMuted} size={20} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, borderRadius: radii.md },
  heading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  headingText: { flex: 1, gap: 3 },
  title: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  subtitle: { color: colors.inkMuted, fontSize: 12 },
  percent: { color: colors.greenDeep, fontSize: 18, fontWeight: '900' },
  track: {
    height: 8,
    overflow: 'hidden',
    borderRadius: 999,
    backgroundColor: colors.border,
  },
  progress: { height: '100%', borderRadius: 999, backgroundColor: colors.greenDeep },
  toggle: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: radii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  toggleText: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  toggleLabel: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  toggleCount: { color: colors.inkMuted, fontSize: 13, fontWeight: '800' },
  pressed: { opacity: 0.72, transform: [{ scale: 0.99 }] },
});
