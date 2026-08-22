import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  FlatList,
  StyleSheet,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';

import { useRouteFocus } from '@/core/query/use-route-focus';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { requestSync } from '@/core/sync/sync-trigger';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import {
  acknowledgeAttendanceNeedsReview,
  acknowledgeRejectedAttendance,
  listAttendanceNeedsReview,
  retryAttendanceNeedsReview,
  type AttendanceNeedsReviewItem,
} from '@/features/coordinator/data/attendance-queue';
import {
  attendanceIssueExplanation,
  listRejectedAttendanceIssues,
  type RejectedAttendanceIssue,
} from '@/features/coordinator/data/attendance-scan-issues';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';

type ScanIssue =
  | Readonly<{ kind: 'needs_review'; value: AttendanceNeedsReviewItem }>
  | Readonly<{ kind: 'rejected'; value: RejectedAttendanceIssue }>;

function readableTimestamp(value: string): string {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : 'Time unavailable';
}

function readScanIssues(tripId: string) {
  return Promise.all([
    listAttendanceNeedsReview(tripId),
    listRejectedAttendanceIssues(tripId),
  ]);
}

export default function CoordinatorScanIssuesScreen() {
  const trips = useCoordinatorTrips();
  const selectedTripId = trips.selectedTripId;
  const focused = useRouteFocus();
  const loadVersion = useRef(0);
  const [needsReview, setNeedsReview] = useState<AttendanceNeedsReviewItem[]>([]);
  const [rejected, setRejected] = useState<RejectedAttendanceIssue[]>([]);
  const [loadedTripId, setLoadedTripId] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const tripId = selectedTripId;
    const version = loadVersion.current + 1;
    loadVersion.current = version;
    if (!tripId) return;
    try {
      const [reviewItems, rejectedItems] = await readScanIssues(tripId);
      if (loadVersion.current !== version) return;
      setNeedsReview(reviewItems);
      setRejected(rejectedItems);
      setLoadFailed(false);
    } catch {
      if (loadVersion.current === version) setLoadFailed(true);
    } finally {
      if (loadVersion.current === version) setLoadedTripId(tripId);
    }
  }, [selectedTripId]);

  useEffect(() => {
    const tripId = selectedTripId;
    const version = loadVersion.current + 1;
    loadVersion.current = version;
    if (focused && tripId) {
      void readScanIssues(tripId)
        .then(([reviewItems, rejectedItems]) => {
          if (loadVersion.current !== version) return;
          setNeedsReview(reviewItems);
          setRejected(rejectedItems);
          setLoadFailed(false);
        })
        .catch(() => {
          if (loadVersion.current === version) setLoadFailed(true);
        })
        .finally(() => {
          if (loadVersion.current === version) setLoadedTripId(tripId);
        });
    }
    return () => {
      loadVersion.current += 1;
    };
  }, [focused, selectedTripId]);

  const currentTripLoaded = loadedTripId === selectedTripId;
  const loading = Boolean(selectedTripId) && !currentTripLoaded;
  const error = !selectedTripId || (currentTripLoaded && loadFailed);
  const visibleRejectedCount = currentTripLoaded ? rejected.length : 0;
  const items = useMemo<ScanIssue[]>(() => {
    if (!currentTripLoaded) return [];
    return [
      ...needsReview.map((value): ScanIssue => ({ kind: 'needs_review', value })),
      ...rejected.map((value): ScanIssue => ({ kind: 'rejected', value })),
    ];
  }, [currentTripLoaded, needsReview, rejected]);

  const retryIssue = useCallback(async (item: AttendanceNeedsReviewItem) => {
    const tripId = selectedTripId;
    if (!tripId || busyKey) return;
    setBusyKey(item.idempotencyKey);
    setMessage(null);
    try {
      await requestSync({ scope: 'trip', tripId, reason: 'manual-scan-issue-retry' });
      await retryAttendanceNeedsReview(tripId, item.idempotencyKey);
      setMessage('The saved scan was synchronized and retried. The current result is shown below.');
      await load();
    } catch {
      setMessage('The retry could not complete. Connect to the internet, synchronize, and try again.');
    } finally {
      setBusyKey(null);
    }
  }, [busyKey, load, selectedTripId]);

  const discardReviewIssue = useCallback((item: AttendanceNeedsReviewItem) => {
    const tripId = selectedTripId;
    if (!tripId || busyKey) return;
    Alert.alert(
      'Discard this saved scan?',
      'This removes the unresolved scan from this device. It cannot be recovered or uploaded later.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Discard scan',
          style: 'destructive',
          onPress: () => {
            setBusyKey(item.idempotencyKey);
            setMessage(null);
            void acknowledgeAttendanceNeedsReview(tripId, item.idempotencyKey)
              .then(() => {
                setMessage('The unresolved scan was explicitly discarded.');
                return load();
              })
              .catch(() => setMessage('The scan could not be discarded. Try again.'))
              .finally(() => setBusyKey(null));
          },
        },
      ],
    );
  }, [busyKey, load, selectedTripId]);

  const clearRejected = useCallback(() => {
    const tripId = selectedTripId;
    if (!tripId || visibleRejectedCount === 0 || busyKey) return;
    Alert.alert(
      'Acknowledge terminal scan issues?',
      'Their QR payloads are already securely erased. This removes the remaining reason and timing records from this device.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Acknowledge issues',
          style: 'destructive',
          onPress: () => {
            setBusyKey('rejected');
            setMessage(null);
            void acknowledgeRejectedAttendance(tripId)
              .then((count) => {
                setMessage(`${count} terminal scan issue${count === 1 ? '' : 's'} acknowledged.`);
                return load();
              })
              .catch(() => setMessage('Terminal issues could not be acknowledged. Try again.'))
              .finally(() => setBusyKey(null));
          },
        },
      ],
    );
  }, [busyKey, load, selectedTripId, visibleRejectedCount]);

  const renderIssue = useCallback<ListRenderItem<ScanIssue>>(({ item, index }) => {
    const issue = item.value;
    const retryAvailable = item.kind === 'needs_review';
    return (
      <GlassCard style={styles.issueCard}>
        <View style={styles.issueHeading}>
          <Text style={styles.issueTitle}>
            {retryAvailable ? 'Review and retry' : 'Not accepted'} #{index + 1}
          </Text>
          <Text style={retryAvailable ? styles.reviewState : styles.rejectedState}>
            {retryAvailable ? 'ACTION REQUIRED' : 'TERMINAL'}
          </Text>
        </View>
        <Text style={styles.explanation}>{attendanceIssueExplanation(issue.reasonCode)}</Text>
        <Text style={styles.metadata}>
          Saved {readableTimestamp(issue.createdAt)} · Updated {readableTimestamp(issue.updatedAt)} · Attempts {issue.attemptCount}
        </Text>
        <Text style={styles.eventId}>Reference {issue.idempotencyKey.slice(-8).toUpperCase()}</Text>
        {retryAvailable ? (
          <View style={styles.actions}>
            <PrimaryButton
              label="Sync and retry"
              loading={busyKey === issue.idempotencyKey}
              tone="secondary"
              onPress={() => void retryIssue(item.value)}
            />
            <PrimaryButton
              label="Discard saved scan"
              disabled={busyKey !== null}
              tone="danger"
              onPress={() => discardReviewIssue(item.value)}
            />
          </View>
        ) : null}
      </GlassCard>
    );
  }, [busyKey, discardReviewIssue, retryIssue]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={items}
        keyExtractor={(item) => `${item.kind}:${item.value.idempotencyKey}`}
        renderItem={renderIssue}
        {...MOBILE_LIST_WINDOWING.interactive}
        contentContainerStyle={styles.list}
        ListHeaderComponent={(
          <View style={styles.header}>
            <OperationHeader
              title="Scan Issues"
              subtitle={trips.selectedTrip?.name || 'Selected group'}
            />
            <GlassCard style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>{items.length} unresolved records</Text>
              <Text style={styles.summaryCopy}>
                Retried items keep the same idempotency key. Terminal QR payloads are erased automatically; only safe support metadata remains.
              </Text>
            </GlassCard>
            {loading ? <ContentLoading label="Loading scan issues" /> : null}
            {error ? <ContentError message="Scan issues could not be read from encrypted storage." onRetry={() => void load()} /> : null}
            {message ? <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text> : null}
          </View>
        )}
        ListEmptyComponent={!loading && !error ? (
          <ContentEmpty title="No scan issues" message="Every saved scan is confirmed or still in the automatic upload queue." />
        ) : null}
        ListFooterComponent={visibleRejectedCount > 0 ? (
          <View style={styles.footer}>
            <PrimaryButton
              label="Acknowledge terminal issues"
              loading={busyKey === 'rejected'}
              tone="danger"
              onPress={clearRejected}
            />
          </View>
        ) : null}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: 104, gap: spacing.md },
  header: { gap: spacing.md },
  summaryCard: { gap: spacing.sm, borderRadius: radii.md },
  summaryTitle: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  summaryCopy: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
  issueCard: { gap: spacing.md, borderRadius: radii.md },
  issueHeading: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  issueTitle: { flex: 1, color: colors.ink, fontSize: 15, fontWeight: '900' },
  reviewState: { color: colors.warning, fontSize: 10, fontWeight: '900' },
  rejectedState: { color: colors.danger, fontSize: 10, fontWeight: '900' },
  explanation: { color: colors.ink, fontSize: 13, lineHeight: 19 },
  metadata: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  eventId: { color: colors.inkMuted, fontSize: 10, fontWeight: '800' },
  actions: { gap: spacing.sm },
  message: { color: colors.ink, fontSize: 13, fontWeight: '700', lineHeight: 19 },
  footer: { paddingTop: spacing.sm },
});
