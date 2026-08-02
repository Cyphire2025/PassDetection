import { CameraView, useCameraPermissions, type BarcodeScanningResult } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import Flashlight from 'lucide-react-native/icons/flashlight';
import FlashlightOff from 'lucide-react-native/icons/flashlight-off';
import ScanLine from 'lucide-react-native/icons/scan-line';
import TriangleAlert from 'lucide-react-native/icons/triangle-alert';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import type { AttendanceSession } from '@/features/coordinator/api/coordinator-contracts';
import { enqueueQrScan, drainAttendanceQueue } from '@/features/coordinator/data/attendance-queue';
import { createAttendanceSession, selectAttendanceSession } from '@/features/coordinator/data/attendance-sessions';
import { useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

type ScanState = { tone: 'good' | 'warning' | 'danger'; message: string } | null;

function validAttendanceQr(value: string): boolean {
  return /^pdatt:[A-Za-z0-9_-]{43}$/.test(value);
}

export default function CoordinatorScanScreen() {
  const trips = useCoordinatorTrips();
  const sessions = useAttendanceSessions(trips.selectedTripId);
  const availableSessions = useMemo(
    () => (sessions.data?.items ?? []).filter((session) => session.status === 'draft' || session.status === 'active'),
    [sessions.data?.items],
  );
  const selectedSession = availableSessions.find(
    (session) => session.id === sessions.data?.selectedSessionId,
  ) ?? null;
  const [permission, requestPermission] = useCameraPermissions();
  const [torch, setTorch] = useState(false);
  const [scanState, setScanState] = useState<ScanState>(null);
  const [activityName, setActivityName] = useState('');
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityBusy, setActivityBusy] = useState(false);
  const [managingActivity, setManagingActivity] = useState(false);
  const [optimisticScans, setOptimisticScans] = useState({
    sessionId: null as string | null,
    baseline: 0,
    count: 0,
  });
  const scanLock = useRef(false);
  const lastScan = useRef<{ value: string; at: number } | null>(null);
  const drainTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (drainTimer.current) clearTimeout(drainTimer.current);
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
  }, []);

  const scheduleDrain = useCallback((tripId: string) => {
    if (drainTimer.current) clearTimeout(drainTimer.current);
    drainTimer.current = setTimeout(() => {
      drainTimer.current = null;
      void drainAttendanceQueue(tripId)
        .then(() => sessions.refetch())
        .catch(() => undefined);
    }, 350);
  }, [sessions]);

  const showFeedback = useCallback((next: Exclude<ScanState, null>) => {
    setScanState(next);
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    feedbackTimer.current = setTimeout(() => setScanState(null), 850);
  }, []);

  const handleScan = useCallback(async ({ data }: BarcodeScanningResult) => {
    const tripId = trips.selectedTripId;
    if (!tripId || !selectedSession || scanLock.current) return;
    const now = Date.now();
    if (lastScan.current?.value === data && now - lastScan.current.at < 2_000) return;
    lastScan.current = { value: data, at: now };
    scanLock.current = true;
    try {
      if (!validAttendanceQr(data)) {
        showFeedback({ tone: 'danger', message: 'Invalid attendance QR' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        return;
      }
      const queued = await enqueueQrScan(tripId, selectedSession.id, data);
      if (queued.duplicate) {
        showFeedback({ tone: 'warning', message: 'Already scanned for this activity' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      } else {
        setOptimisticScans((current) => (
          current.sessionId === selectedSession.id
            ? { ...current, count: current.count + 1 }
            : { sessionId: selectedSession.id, baseline: selectedSession.scanned_count, count: 1 }
        ));
        showFeedback({ tone: 'good', message: 'Checked in' });
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        scheduleDrain(tripId);
      }
    } catch {
      showFeedback({ tone: 'danger', message: 'Scan was not saved — scan again' });
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    } finally {
      setTimeout(() => {
        scanLock.current = false;
      }, 180);
    }
  }, [scheduleDrain, selectedSession, showFeedback, trips.selectedTripId]);

  const createActivity = useCallback(async () => {
    const tripId = trips.selectedTripId;
    const name = activityName.trim();
    if (!tripId || name.length < 2) {
      setActivityError('Enter an activity name of at least 2 characters.');
      return;
    }
    setActivityBusy(true);
    setActivityError(null);
    try {
      await createAttendanceSession(tripId, name);
      setActivityName('');
      await sessions.refetch();
      setManagingActivity(false);
    } catch (caught) {
      setActivityError(caught instanceof Error ? caught.message : 'The attendance activity could not be created.');
    } finally {
      setActivityBusy(false);
    }
  }, [activityName, sessions, trips.selectedTripId]);

  const chooseActivity = useCallback(async (session: AttendanceSession) => {
    if (!trips.selectedTripId) return;
    setActivityBusy(true);
    setActivityError(null);
    try {
      await selectAttendanceSession(trips.selectedTripId, session.id);
      await sessions.refetch();
      setManagingActivity(false);
    } catch (caught) {
      setActivityError(caught instanceof Error ? caught.message : 'The attendance activity could not be selected.');
    } finally {
      setActivityBusy(false);
    }
  }, [sessions, trips.selectedTripId]);

  const localTotal = optimisticScans.sessionId === selectedSession?.id
    ? optimisticScans.baseline + optimisticScans.count
    : selectedSession?.scanned_count ?? 0;
  const liveCount = Math.max(selectedSession?.scanned_count ?? 0, localTotal);

  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader
        eyebrow="Attendance"
        title="Scan QR"
        subtitle={trips.selectedTrip?.name || 'Selected group'}
      />
      {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
      {sessions.isError ? (
        <ContentError message="Attendance activities are not available on this device." onRetry={() => void sessions.refetch()} />
      ) : null}

      {managingActivity || !selectedSession ? (
        <View style={styles.activityWorkspace}>
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
            <View style={styles.activities}>
              <Text accessibilityRole="header" style={styles.activityTitle}>Continue an activity</Text>
              {availableSessions.map((session) => (
                <Pressable
                  key={session.id}
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
              ))}
            </View>
          ) : (
            !sessions.isPending && !sessions.isError
              ? <ContentEmpty title="No active activities" message="Create one to start scanning." />
              : null
          )}
        </View>
      ) : (
        <>
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
                barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
                onBarcodeScanned={(result) => void handleScan(result)}
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
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  activityWorkspace: { gap: spacing.lg },
  createCard: { gap: spacing.md, borderRadius: radii.md },
  activityTitle: { color: colors.ink, fontSize: 18, fontWeight: '900' },
  activities: { gap: spacing.sm },
  activityRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, borderRadius: radii.md },
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
  pressed: { opacity: 0.68 },
});
