import {
  CameraView,
  useCameraPermissions,
  type BarcodeScanningResult,
  type CameraViewProps,
} from 'expo-camera';
import * as Haptics from 'expo-haptics';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import Flashlight from 'lucide-react-native/icons/flashlight';
import FlashlightOff from 'lucide-react-native/icons/flashlight-off';
import ScanLine from 'lucide-react-native/icons/scan-line';
import TriangleAlert from 'lucide-react-native/icons/triangle-alert';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import type { AttendanceSession } from '@/features/coordinator/api/coordinator-contracts';
import {
  attendanceSessionQueueStatus,
  enqueueQrScan,
  drainAttendanceQueue,
} from '@/features/coordinator/data/attendance-queue';
import { createAttendanceSession, selectAttendanceSession } from '@/features/coordinator/data/attendance-sessions';
import {
  EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
  attendanceScanTimestamp,
  confirmedAttendanceCount,
  isRapidRepeatScan,
  recordOptimisticAttendanceScan,
  restorePendingAttendanceScans,
  settleOptimisticAttendanceScans,
  type RecentAttendanceScan,
} from '@/features/coordinator/data/scan-policy';
import { useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

type ScanState = { tone: 'good' | 'warning' | 'danger'; message: string } | null;

const ATTENDANCE_BARCODE_SETTINGS: NonNullable<CameraViewProps['barcodeScannerSettings']> = {
  barcodeTypes: ['qr'],
};

function validAttendanceQr(value: string): boolean {
  return /^pdatt:[A-Za-z0-9_-]{43}$/.test(value);
}

export default function CoordinatorScanScreen() {
  const manualRefresh = useManualRefresh();
  const trips = useCoordinatorTrips();
  const sessions = useAttendanceSessions(trips.selectedTripId);
  const availableSessions = useMemo(
    () => (sessions.data?.items ?? []).filter((session) => session.status === 'draft' || session.status === 'active'),
    [sessions.data?.items],
  );
  const selectedSession = availableSessions.find(
    (session) => session.id === sessions.data?.selectedSessionId,
  ) ?? null;
  const selectedSessionId = selectedSession?.id ?? null;
  const selectedSessionScannedCount = selectedSession?.scanned_count ?? 0;
  const [permission, requestPermission] = useCameraPermissions();
  const [torch, setTorch] = useState(false);
  const [scanState, setScanState] = useState<ScanState>(null);
  const [activityName, setActivityName] = useState('');
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityBusy, setActivityBusy] = useState(false);
  const [managingActivity, setManagingActivity] = useState(false);
  const [optimisticScans, setOptimisticScans] = useState({
    ...EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
  });
  const scanLock = useRef(false);
  const activityMutationLock = useRef(false);
  const lastScan = useRef<RecentAttendanceScan | null>(null);
  const drainTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scanUnlockTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const drainRunning = useRef(false);
  const pendingDrainTrips = useRef(new Set<string>());
  const queueStatusLoad = useRef(0);
  const flushDrainRef = useRef<() => void>(() => undefined);
  const selectedTripIdRef = useRef(trips.selectedTripId);
  const selectedSessionRef = useRef<AttendanceSession | null>(selectedSession);
  const refetchSessionsRef = useRef(sessions.refetch);

  useEffect(() => {
    selectedTripIdRef.current = trips.selectedTripId;
    selectedSessionRef.current = selectedSession;
    refetchSessionsRef.current = sessions.refetch;
  }, [selectedSession, sessions.refetch, trips.selectedTripId]);

  useEffect(() => () => {
    if (drainTimer.current) clearTimeout(drainTimer.current);
    if (scanUnlockTimer.current) clearTimeout(scanUnlockTimer.current);
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    pendingDrainTrips.current.clear();
  }, []);

  useEffect(() => {
    lastScan.current = null;
    scanLock.current = false;
    if (scanUnlockTimer.current) {
      clearTimeout(scanUnlockTimer.current);
      scanUnlockTimer.current = null;
    }
    activityMutationLock.current = false;
  }, [selectedSession?.id, trips.selectedTripId]);

  useEffect(() => {
    const loadId = queueStatusLoad.current + 1;
    queueStatusLoad.current = loadId;
    const tripId = trips.selectedTripId;
    if (!tripId || !selectedSessionId) return;
    void attendanceSessionQueueStatus(tripId, selectedSessionId)
      .then((status) => {
        if (
          queueStatusLoad.current !== loadId
          || selectedTripIdRef.current !== tripId
          || selectedSessionRef.current?.id !== selectedSessionId
        ) return;
        setOptimisticScans((current) => {
          if (current.sessionId === null && status.awaitingConfirmation === 0) return current;
          return restorePendingAttendanceScans(
            current,
            selectedSessionId,
            selectedSessionScannedCount,
            status.awaitingConfirmation,
          );
        });
      })
      .catch(() => undefined);
  }, [selectedSessionId, selectedSessionScannedCount, trips.selectedTripId]);

  const showFeedback = useCallback((next: Exclude<ScanState, null>) => {
    setScanState(next);
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    feedbackTimer.current = setTimeout(() => setScanState(null), 1_800);
  }, []);

  const ensureDrainScheduled = useCallback(() => {
    if (drainTimer.current || drainRunning.current || pendingDrainTrips.current.size === 0) return;
    drainTimer.current = setTimeout(() => {
      drainTimer.current = null;
      flushDrainRef.current();
    }, 350);
  }, []);

  const flushDrains = useCallback(async () => {
    if (drainRunning.current) return;
    drainRunning.current = true;
    const drainedTrips = new Set<string>();
    const settledByTrip = new Map<string, Record<string, number>>();
    const confirmedByTrip = new Map<string, Record<string, number>>();
    const newlyAcceptedByTrip = new Map<string, Record<string, number>>();
    const rejectedByTrip = new Map<string, Record<string, number>>();
    try {
      while (pendingDrainTrips.current.size > 0) {
        const batch = [...pendingDrainTrips.current];
        pendingDrainTrips.current.clear();
        const results = await Promise.allSettled(
          batch.map((tripId) => drainAttendanceQueue(tripId)),
        );
        results.forEach((result, index) => {
          const tripId = batch[index];
          if (result.status !== 'fulfilled' || !tripId) return;
          drainedTrips.add(tripId);
          const fields = [
            [settledByTrip, result.value.settledBySession],
            [confirmedByTrip, result.value.confirmedBySession],
            [newlyAcceptedByTrip, result.value.newlyAcceptedBySession],
            [rejectedByTrip, result.value.rejectedBySession],
          ] as const;
          for (const [target, source] of fields) {
            const counts = target.get(tripId) ?? {};
            for (const [sessionId, count] of Object.entries(source)) {
              counts[sessionId] = (counts[sessionId] ?? 0) + count;
            }
            target.set(tripId, counts);
          }
        });
      }
      const activeTripId = selectedTripIdRef.current;
      if (activeTripId && drainedTrips.has(activeTripId)) {
        const activeSession = selectedSessionRef.current;
        if (activeSession) {
          let serverCount = activeSession.scanned_count;
          try {
            const refreshed = await refetchSessionsRef.current();
            serverCount = refreshed.data?.items.find(
              (item) => item.id === activeSession.id,
            )?.scanned_count ?? serverCount;
          } catch {
            // The server acknowledgement below is still authoritative if the follow-up read is offline.
          }
          let durablePendingCount: number | null = null;
          try {
            durablePendingCount = (
              await attendanceSessionQueueStatus(activeTripId, activeSession.id)
            ).awaitingConfirmation;
          } catch {
            // Keep the in-memory pending count; the next queue read will restore the durable value.
          }
          if (
            selectedTripIdRef.current !== activeTripId
            || selectedSessionRef.current?.id !== activeSession.id
          ) return;
          const settledCount = settledByTrip.get(activeTripId)?.[activeSession.id] ?? 0;
          const newlyAcceptedCount = newlyAcceptedByTrip
            .get(activeTripId)?.[activeSession.id] ?? 0;
          setOptimisticScans((current) => {
            const settled = settleOptimisticAttendanceScans(
              current,
              activeSession.id,
              serverCount,
              settledCount,
              newlyAcceptedCount,
            );
            return durablePendingCount === null
              ? settled
              : restorePendingAttendanceScans(
                  settled,
                  activeSession.id,
                  serverCount,
                  durablePendingCount,
                );
          });

          const confirmedCount = confirmedByTrip.get(activeTripId)?.[activeSession.id] ?? 0;
          const rejectedCount = rejectedByTrip.get(activeTripId)?.[activeSession.id] ?? 0;
          if (rejectedCount > 0) {
            const confirmedPrefix = confirmedCount > 0 ? `${confirmedCount} confirmed; ` : '';
            showFeedback({
              tone: 'danger',
              message: `${confirmedPrefix}${rejectedCount} not accepted — review the activity`,
            });
            void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
          } else if (confirmedCount > 0) {
            showFeedback({
              tone: 'good',
              message: confirmedCount === 1 ? 'Checked in' : `${confirmedCount} check-ins confirmed`,
            });
            void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          }
        }
      }
    } finally {
      drainRunning.current = false;
      ensureDrainScheduled();
    }
  }, [ensureDrainScheduled, showFeedback]);

  useEffect(() => {
    flushDrainRef.current = () => {
      void flushDrains();
    };
  }, [flushDrains]);

  const scheduleDrain = useCallback((tripId: string) => {
    pendingDrainTrips.current.add(tripId);
    ensureDrainScheduled();
  }, [ensureDrainScheduled]);

  const handleScan = useCallback(async ({ data }: BarcodeScanningResult) => {
    const tripId = selectedTripIdRef.current;
    const session = selectedSessionRef.current;
    if (!tripId || !session || scanLock.current) return;
    const now = attendanceScanTimestamp();
    if (isRapidRepeatScan(lastScan.current, session.id, data, now)) return;
    lastScan.current = { sessionId: session.id, value: data, at: now };
    scanLock.current = true;
    try {
      if (!validAttendanceQr(data)) {
        showFeedback({ tone: 'danger', message: 'Invalid attendance QR' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        return;
      }
      const queued = await enqueueQrScan(tripId, session.id, data, {
        assignedCount: session.assigned_count,
      });
      if (queued.status === 'queued') {
        queueStatusLoad.current += 1;
        setOptimisticScans((current) => (
          recordOptimisticAttendanceScan(current, session.id, session.scanned_count)
        ));
        showFeedback({ tone: 'warning', message: 'Saved — confirmation pending' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
        scheduleDrain(tripId);
      } else if (queued.status === 'already_queued') {
        showFeedback({ tone: 'warning', message: 'Already saved — confirmation pending' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
        scheduleDrain(tripId);
      } else if (queued.status === 'already_confirmed') {
        showFeedback({ tone: 'warning', message: 'Already confirmed for this activity' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      } else if (queued.status === 'previously_rejected') {
        showFeedback({ tone: 'danger', message: 'This QR was not accepted earlier — review the activity' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      } else {
        showFeedback({
          tone: 'danger',
          message: 'Unsent scan limit reached — connect and sync before scanning more',
        });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        scheduleDrain(tripId);
      }
    } catch {
      showFeedback({ tone: 'danger', message: 'Scan was not saved — scan again' });
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    } finally {
      if (scanUnlockTimer.current) clearTimeout(scanUnlockTimer.current);
      scanUnlockTimer.current = setTimeout(() => {
        scanUnlockTimer.current = null;
        scanLock.current = false;
      }, 180);
    }
  }, [scheduleDrain, showFeedback]);

  const createActivity = useCallback(async () => {
    const tripId = selectedTripIdRef.current;
    const name = activityName.trim();
    if (activityMutationLock.current) return;
    if (!tripId || name.length < 2) {
      setActivityError('Enter an activity name of at least 2 characters.');
      return;
    }
    activityMutationLock.current = true;
    setActivityBusy(true);
    setActivityError(null);
    try {
      await createAttendanceSession(tripId, name);
      setActivityName('');
      await refetchSessionsRef.current();
      if (selectedTripIdRef.current === tripId) setManagingActivity(false);
    } catch (caught) {
      setActivityError(userFacingErrorMessage(caught, 'The attendance activity could not be created.'));
    } finally {
      activityMutationLock.current = false;
      setActivityBusy(false);
    }
  }, [activityName]);

  const chooseActivity = useCallback(async (session: AttendanceSession) => {
    const tripId = selectedTripIdRef.current;
    if (!tripId || activityMutationLock.current) return;
    activityMutationLock.current = true;
    setActivityBusy(true);
    setActivityError(null);
    try {
      await selectAttendanceSession(tripId, session.id);
      await refetchSessionsRef.current();
      if (selectedTripIdRef.current === tripId) setManagingActivity(false);
    } catch (caught) {
      setActivityError(userFacingErrorMessage(caught, 'The attendance activity could not be selected.'));
    } finally {
      activityMutationLock.current = false;
      setActivityBusy(false);
    }
  }, []);

  const liveCount = selectedSession
    ? confirmedAttendanceCount(optimisticScans, selectedSession.id, selectedSession.scanned_count)
    : 0;
  const awaitingConfirmation = selectedSession && optimisticScans.sessionId === selectedSession.id
    ? optimisticScans.pendingCount
    : 0;
  const activityManagementVisible = managingActivity || !selectedSession;
  const refreshActivities = useCallback(
    () => refetchSessionsRef.current(),
    [],
  );
  const activityRefreshEnabled = activityManagementVisible && !activityName.trim() && !activityBusy;
  const renderActivity = useCallback<ListRenderItem<AttendanceSession>>(({ item: session }) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Continue ${session.name}`}
      disabled={activityBusy}
      onPress={() => void chooseActivity(session)}
      style={({ pressed }) => pressed && styles.pressed}>
      <GlassCard style={styles.activityRow}>
        <View style={styles.activityText}>
          <Text style={styles.activityName}>{session.name}</Text>
          <Text style={styles.activityMeta}>{session.scanned_count} of {session.assigned_count} scanned</Text>
        </View>
        <Text style={styles.continueLabel}>Select</Text>
      </GlassCard>
    </Pressable>
  ), [activityBusy, chooseActivity]);

  const pageHeader = (
    <PageHeader
      eyebrow="Attendance"
      title="Scan QR"
      subtitle={trips.selectedTrip?.name || 'Selected group'}
      tone="coordinator"
    />
  );
  const queryState = (
    <>
      {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
      {sessions.isError ? (
        <ContentError message="Attendance activities are not available on this device." onRetry={() => void sessions.refetch()} />
      ) : null}
    </>
  );

  if (activityManagementVisible) {
    return (
      <Screen scroll={false} bottomInset={0} contentStyle={styles.listScreen}>
        <FlatList
          testID="scan-activity-list"
          data={availableSessions}
          keyExtractor={(session) => session.id}
          renderItem={renderActivity}
          {...MOBILE_LIST_WINDOWING.interactive}
          contentContainerStyle={styles.activityList}
          {...(activityRefreshEnabled ? {
            refreshing: manualRefresh.isRefreshing,
            onRefresh: () => void manualRefresh.refresh(refreshActivities),
          } : {})}
          ListHeaderComponent={(
            <View style={styles.activityHeader}>
              {pageHeader}
              {queryState}
              <GlassCard style={styles.createCard}>
                <Text style={styles.activityTitle}>Create an activity</Text>
                <TextField
                  label="Activity name"
                  value={activityName}
                  onChangeText={setActivityName}
                  placeholder="Airport reporting"
                  maxLength={160}
                  error={activityError}
                />
                <PrimaryButton label="Create and start scanning" loading={activityBusy} onPress={() => void createActivity()} />
              </GlassCard>
              {availableSessions.length > 0 ? (
                <Text accessibilityRole="header" style={styles.activityTitle}>Continue an activity</Text>
              ) : null}
            </View>
          )}
          ListEmptyComponent={
            !sessions.isPending && !sessions.isError
              ? <ContentEmpty title="No active activities" message="Create one to start scanning." />
              : null
          }
        />
      </Screen>
    );
  }

  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      {pageHeader}
      {queryState}
      <View style={styles.activeHeader}>
        <View style={styles.activityText}>
          <Text style={styles.activeLabel}>Active activity</Text>
          <Text style={styles.activityName}>{selectedSession.name}</Text>
        </View>
        <Pressable accessibilityRole="button" onPress={() => setManagingActivity(true)} style={styles.changeButton}>
          <Text style={styles.changeText}>Change</Text>
        </Pressable>
      </View>

      {!permission?.granted ? (
        <GlassCard style={styles.permission}>
          <ScanLine color={colors.greenDeep} size={30} />
          <Text style={styles.permissionTitle}>Camera access is needed</Text>
          <Text style={styles.permissionMessage}>The camera is used only while scanning attendance QR codes.</Text>
          <PrimaryButton label="Allow camera" onPress={() => void requestPermission()} />
        </GlassCard>
      ) : (
        <View style={styles.cameraFrame}>
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            enableTorch={torch}
            barcodeScannerSettings={ATTENDANCE_BARCODE_SETTINGS}
            onBarcodeScanned={handleScan}
          />
          <View pointerEvents="none" style={styles.guide} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={torch ? 'Turn flashlight off' : 'Turn flashlight on'}
            onPress={() => setTorch((value) => !value)}
            style={styles.torch}>
            {torch
              ? <FlashlightOff color={colors.white} size={22} />
              : <Flashlight color={colors.white} size={22} />}
          </Pressable>
          {scanState ? (
            <View
              accessibilityLiveRegion="polite"
              style={[
                styles.feedback,
                scanState.tone === 'danger' && styles.feedbackDanger,
                scanState.tone === 'warning' && styles.feedbackWarning,
              ]}>
              {scanState.tone === 'good'
                ? <CheckCircle2 color={colors.white} size={21} />
                : <TriangleAlert color={colors.white} size={21} />}
              <Text style={styles.feedbackText}>{scanState.message}</Text>
            </View>
          ) : null}
        </View>
      )}
      <Text accessibilityLiveRegion="polite" style={styles.liveCount}>
        {liveCount.toLocaleString()} of {selectedSession.assigned_count.toLocaleString()} scanned
      </Text>
      {awaitingConfirmation > 0 ? (
        <Text accessibilityLiveRegion="polite" style={styles.pendingStatus}>
          {awaitingConfirmation.toLocaleString()} saved on this device — awaiting server confirmation
        </Text>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  listScreen: { paddingHorizontal: 0 },
  activityList: { paddingHorizontal: spacing.lg, paddingBottom: 104 },
  activityHeader: { gap: spacing.lg, paddingBottom: spacing.lg },
  createCard: { gap: spacing.md, borderRadius: radii.md },
  activityTitle: { color: colors.ink, fontSize: 18, fontWeight: '900' },
  activityRow: { marginBottom: spacing.sm, flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, borderRadius: radii.md },
  activityText: { flex: 1, gap: 3 },
  activityName: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  activityMeta: { color: colors.inkMuted, fontSize: 12 },
  continueLabel: { color: colors.greenDeep, fontSize: 13, fontWeight: '900' },
  activeHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  activeLabel: { color: colors.inkMuted, fontSize: 11, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.8 },
  changeButton: { minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.md },
  changeText: { color: colors.greenDeep, fontSize: 14, fontWeight: '900' },
  permission: { gap: spacing.md, alignItems: 'center' },
  permissionTitle: { color: colors.ink, fontSize: 18, fontWeight: '800' },
  permissionMessage: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center' },
  cameraFrame: { height: 390, overflow: 'hidden', borderRadius: radii.lg, backgroundColor: colors.ink },
  guide: { position: 'absolute', width: 230, height: 230, alignSelf: 'center', top: 80, borderWidth: 3, borderColor: colors.white, borderRadius: 28 },
  torch: { position: 'absolute', right: spacing.lg, top: spacing.lg, width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center' },
  feedback: {
    position: 'absolute',
    left: spacing.lg,
    right: spacing.lg,
    bottom: spacing.lg,
    minHeight: 52,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: 'rgba(63,112,31,0.92)',
  },
  feedbackDanger: { backgroundColor: 'rgba(184,64,77,0.94)' },
  feedbackWarning: { backgroundColor: 'rgba(166,106,18,0.94)' },
  feedbackText: { color: colors.white, fontSize: 15, fontWeight: '900', textAlign: 'center' },
  liveCount: { color: colors.ink, textAlign: 'center', fontSize: 22, fontWeight: '900' },
  pendingStatus: { color: colors.inkMuted, textAlign: 'center', fontSize: 13, fontWeight: '700' },
  pressed: { opacity: 0.68 },
});
