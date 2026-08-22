import { useRouter, type Href } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useRouteFocus } from '@/core/query/use-route-focus';
import { recordAttendanceReconciliationAssessment } from '@/core/observability/attendance-observability';
import { requestSync } from '@/core/sync/sync-trigger';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';
import type { AttendanceSession } from '@/features/coordinator/api/coordinator-contracts';
import {
  publishAttendanceCloseoutCheckpoint,
  type AttendanceCloseoutCheckpointResponse,
} from '@/features/coordinator/data/attendance-closeout-checkpoint';
import {
  attendanceSessionQueueStatus,
  drainAttendanceQueue,
  type AttendanceSessionQueueStatus,
} from '@/features/coordinator/data/attendance-queue';

const SCAN_ISSUES_ROUTE = '/(coordinator)/operations/scan-issues' as Href;
const CLOSEOUT_CHECKPOINT_REFRESH_MS = 30_000;

export type AttendanceReconciliationAssessment = Readonly<{
  confirmed: number;
  expected: number;
  message: string;
  missing: number;
  status: 'ready' | 'blocked';
}>;

export function assessAttendanceReconciliation(
  confirmed: number,
  expected: number,
  queue: AttendanceSessionQueueStatus | null,
): AttendanceReconciliationAssessment {
  const safeCounts = Number.isSafeInteger(confirmed)
    && Number.isSafeInteger(expected)
    && confirmed >= 0
    && expected >= 0
    && confirmed <= expected;
  const missing = safeCounts ? expected - confirmed : Math.max(0, expected);
  if (!safeCounts || !queue) {
    return {
      confirmed,
      expected,
      missing,
      status: 'blocked',
      message: 'Closeout evidence could not be verified on this device.',
    };
  }
  if (queue.needsReview > 0) {
    return {
      confirmed,
      expected,
      missing,
      status: 'blocked',
      message: `${queue.needsReview} scan issue${queue.needsReview === 1 ? '' : 's'} must be resolved.`,
    };
  }
  if (queue.awaitingConfirmation > 0) {
    return {
      confirmed,
      expected,
      missing,
      status: 'blocked',
      message: `${queue.awaitingConfirmation} saved scan${queue.awaitingConfirmation === 1 ? '' : 's'} still await server confirmation.`,
    };
  }
  if (confirmed !== expected) {
    return {
      confirmed,
      expected,
      missing,
      status: 'blocked',
      message: `${missing} assigned passenger${missing === 1 ? '' : 's'} remain unconfirmed.`,
    };
  }
  return {
    confirmed,
    expected,
    missing: 0,
    status: 'ready',
    message: 'Server-confirmed count matches the assigned count and this device queue is clear.',
  };
}

type Props = Readonly<{
  onRefresh: () => Promise<unknown>;
  session: AttendanceSession;
  tripId: string;
}>;

export function AttendanceReconciliationCard({ onRefresh, session, tripId }: Props) {
  const router = useRouter();
  const focused = useRouteFocus();
  const evidenceKey = `${tripId}:${session.id}:${session.scanned_count}:${session.assigned_count}`;
  const [queueEvidence, setQueueEvidence] = useState<Readonly<{
    key: string;
    status: AttendanceSessionQueueStatus | null;
  }> | null>(null);
  const checkpointKey = `${tripId}:${session.id}`;
  const [checkpointEvidence, setCheckpointEvidence] = useState<Readonly<{
    key: string;
    report: AttendanceCloseoutCheckpointResponse | null;
  }> | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (!focused) return;
    let active = true;
    void attendanceSessionQueueStatus(tripId, session.id)
      .then((status) => {
        if (active) setQueueEvidence({ key: evidenceKey, status });
      })
      .catch(() => {
        if (active) setQueueEvidence({ key: evidenceKey, status: null });
      });
    return () => {
      active = false;
    };
  }, [evidenceKey, focused, session.id, tripId]);

  useEffect(() => {
    if (!focused || queueEvidence?.key !== evidenceKey) return;
    recordAttendanceReconciliationAssessment(
      session.scanned_count,
      session.assigned_count,
      queueEvidence.status,
    );
  }, [evidenceKey, focused, queueEvidence, session.assigned_count, session.scanned_count]);

  useEffect(() => {
    if (!focused || session.status !== 'active') return;
    let active = true;
    let publishing = false;
    const publish = async () => {
      if (publishing) return;
      publishing = true;
      try {
        const report = await publishAttendanceCloseoutCheckpoint(tripId, session.id);
        if (active) setCheckpointEvidence({ key: checkpointKey, report });
      } catch {
        if (active) setCheckpointEvidence({ key: checkpointKey, report: null });
      } finally {
        publishing = false;
      }
    };
    void publish();
    const refreshTimer = setInterval(() => void publish(), CLOSEOUT_CHECKPOINT_REFRESH_MS);
    return () => {
      active = false;
      clearInterval(refreshTimer);
    };
  }, [checkpointKey, focused, session.id, session.status, tripId]);

  const queue = focused && queueEvidence?.key === evidenceKey
    ? queueEvidence.status
    : null;
  const assessment = assessAttendanceReconciliation(
    session.scanned_count,
    session.assigned_count,
    queue,
  );
  const checkpoint = focused && checkpointEvidence?.key === checkpointKey
    ? checkpointEvidence.report
    : null;
  const checkpointUnresolved = checkpoint
    ? checkpoint.pending_count
      + checkpoint.sending_count
      + checkpoint.retryable_count
      + checkpoint.needs_review_count
      + checkpoint.unreviewed_rejected_count
    : null;

  const synchronizeAndRecheck = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      await drainAttendanceQueue(tripId);
      await requestSync({ scope: 'trip', tripId, reason: 'attendance-final-reconciliation' });
      await onRefresh();
      const status = await attendanceSessionQueueStatus(tripId, session.id);
      setQueueEvidence({ key: evidenceKey, status });
      const report = await publishAttendanceCloseoutCheckpoint(tripId, session.id);
      setCheckpointEvidence({ key: checkpointKey, report });
      setFeedback('Server counts, this runtime queue, and the coordinator checkpoint were refreshed.');
    } catch {
      setCheckpointEvidence({ key: checkpointKey, report: null });
      setFeedback('Closeout could not be refreshed. Connect, synchronize, and try again.');
    } finally {
      setBusy(false);
    }
  }, [busy, checkpointKey, evidenceKey, onRefresh, session.id, tripId]);

  return (
    <GlassCard style={[
      styles.card,
      assessment.status === 'ready' ? styles.readyCard : styles.blockedCard,
    ]}>
      <Text accessibilityRole="header" style={styles.title}>Final reconciliation</Text>
      <View style={styles.countRow}>
        <Text style={styles.count}>{assessment.confirmed.toLocaleString()}</Text>
        <Text style={styles.countLabel}>server confirmed</Text>
        <Text style={styles.count}>{assessment.expected.toLocaleString()}</Text>
        <Text style={styles.countLabel}>assigned</Text>
      </View>
      <Text
        accessibilityLiveRegion="polite"
        style={assessment.status === 'ready' ? styles.readyText : styles.blockedText}>
        {assessment.message}
      </Text>
      <Text style={styles.disclaimer}>
        The manager requires a recent count-only checkpoint from every assigned coordinator account.
        The latest successful report for this account is authoritative. During final reconciliation,
        use one active scanning runtime for this account and reconcile any other runtime before its last report.
      </Text>
      {session.status === 'active' ? (
        checkpoint ? (
          <Text
            accessibilityLiveRegion="polite"
            style={checkpointUnresolved === 0 ? styles.readyText : styles.blockedText}>
            Coordinator checkpoint reported {checkpointUnresolved?.toLocaleString()} unresolved item
            {checkpointUnresolved === 1 ? '' : 's'} at {new Date(checkpoint.reported_at).toLocaleTimeString()}.
          </Text>
        ) : (
          <Text accessibilityLiveRegion="polite" style={styles.blockedText}>
            The coordinator checkpoint is unavailable. The manager close guard will fail closed until a recent report is accepted.
          </Text>
        )
      ) : null}
      {queue?.needsReview ? (
        <PrimaryButton
          label="Open Scan Issues"
          tone="secondary"
          onPress={() => router.push(SCAN_ISSUES_ROUTE)}
        />
      ) : null}
      {assessment.status === 'blocked' ? (
        <PrimaryButton
          label="Sync and recheck"
          loading={busy}
          tone="secondary"
          onPress={() => void synchronizeAndRecheck()}
        />
      ) : null}
      {feedback ? <Text accessibilityLiveRegion="polite" style={styles.feedback}>{feedback}</Text> : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, borderRadius: radii.md, borderWidth: 1 },
  readyCard: { borderColor: colors.green },
  blockedCard: { borderColor: colors.warning },
  title: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  countRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', gap: spacing.sm },
  count: { color: colors.ink, fontSize: 20, fontWeight: '900' },
  countLabel: { color: colors.inkMuted, fontSize: 11, marginRight: spacing.sm },
  readyText: { color: colors.greenDeep, fontSize: 13, fontWeight: '800', lineHeight: 19 },
  blockedText: { color: colors.warning, fontSize: 13, fontWeight: '800', lineHeight: 19 },
  disclaimer: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  feedback: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
});
