import { useRouter, type Href } from 'expo-router';
import { useMemo } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';
import type { CoordinatorEventReadiness } from '@/features/coordinator/hooks/use-event-readiness';

type Props = Readonly<{
  readiness: CoordinatorEventReadiness;
}>;

const SCAN_ISSUES_ROUTE = '/(coordinator)/operations/scan-issues' as Href;

export function EventReadinessCard({ readiness }: Props) {
  const router = useRouter();
  const {
    assessment,
    loading,
    refresh,
    verificationIncomplete,
  } = readiness;

  const heading = loading
    ? 'Checking event readiness'
    : assessment.status === 'ready'
      ? 'Event readiness verified'
      : assessment.status === 'attention'
        ? 'Attention needed before event'
        : 'Not ready for event';
  const summary = loading
    ? 'Verifying roster, authorization, queue, camera, storage, battery, network, and live channel.'
    : assessment.status === 'ready'
      ? 'All required checks are green for the configured 8-hour event window.'
      : assessment.status === 'attention'
        ? 'Required controls are green. CHECK items are advisory, so offline-safe scanning remains available.'
        : 'Resolve every BLOCK item and refresh readiness before scanning.';
  const cardStyle = useMemo(() => (
    loading
      ? styles.blockedCard
      : assessment.status === 'ready'
      ? styles.readyCard
      : assessment.status === 'attention' ? styles.attentionCard : styles.blockedCard
  ), [assessment.status, loading]);
  const scanIssuesBlocked = assessment.checks.some(
    (check) => check.id === 'scan_issues' && check.outcome === 'blocked',
  );

  return (
    <GlassCard style={[styles.card, cardStyle]}>
      <Text accessibilityRole="header" style={styles.heading}>{heading}</Text>
      <Text style={styles.summary}>{summary}</Text>
      {verificationIncomplete && !loading ? (
        <Text accessibilityLiveRegion="polite" style={styles.blockedText}>
          One or more authoritative checks could not be verified. Readiness remains blocked.
        </Text>
      ) : null}
      {!loading ? assessment.checks.map((check) => (
        <View key={check.id} style={styles.checkRow}>
          <Text
            accessibilityLabel={`${check.outcome}: ${check.label}`}
            style={[
              styles.marker,
              check.outcome === 'ready' && styles.readyText,
              check.outcome === 'warning' && styles.attentionText,
              check.outcome === 'blocked' && styles.blockedText,
            ]}>
            {check.outcome === 'ready' ? 'PASS' : check.outcome === 'warning' ? 'CHECK' : 'BLOCK'}
          </Text>
          <View style={styles.checkCopy}>
            <Text style={styles.checkLabel}>{check.label}</Text>
            <Text style={styles.checkMessage}>{check.message}</Text>
          </View>
        </View>
      )) : null}
      {scanIssuesBlocked && !loading ? (
        <PrimaryButton
          label="Open Scan Issues"
          tone="secondary"
          onPress={() => router.push(SCAN_ISSUES_ROUTE)}
        />
      ) : null}
      <PrimaryButton
        label="Refresh readiness"
        loading={loading}
        tone="secondary"
        onPress={() => void refresh()}
      />
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, borderWidth: 1 },
  readyCard: { borderColor: colors.green },
  attentionCard: { borderColor: colors.warning },
  blockedCard: { borderColor: colors.danger },
  heading: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  summary: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
  checkRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  marker: { width: 42, fontSize: 9, fontWeight: '900', paddingTop: 2 },
  checkCopy: { flex: 1, gap: 2 },
  checkLabel: { color: colors.ink, fontSize: 13, fontWeight: '800' },
  checkMessage: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  readyText: { color: colors.greenDeep },
  attentionText: { color: colors.warning },
  blockedText: { color: colors.danger, fontSize: 12, fontWeight: '800' },
});
