import { CameraView, useCameraPermissions, type BarcodeScanningResult } from 'expo-camera';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import Flashlight from 'lucide-react-native/icons/flashlight';
import FlashlightOff from 'lucide-react-native/icons/flashlight-off';
import ScanLine from 'lucide-react-native/icons/scan-line';
import WifiOff from 'lucide-react-native/icons/wifi-off';
import { useCallback, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ContentEmpty } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import { attendanceQueueCounts, drainAttendanceQueue, enqueueQrScan } from '@/features/coordinator/data/attendance-queue';
import { useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';

type ScanState = { tone: 'good' | 'warning' | 'danger'; message: string } | null;

function validAttendanceQr(value: string): boolean {
  return /^pdatt:[A-Za-z0-9_-]{43}$/.test(value);
}

export default function CoordinatorScanScreen() {
  const trips = useTrips();
  const sessions = useAttendanceSessions(trips.selectedTripId);
  const selectedSession = sessions.data?.items.find(
    (session) => session.id === sessions.data.selectedSessionId,
  ) ?? null;
  const [permission, requestPermission] = useCameraPermissions();
  const [torch, setTorch] = useState(false);
  const [scanState, setScanState] = useState<ScanState>(null);
  const [pending, setPending] = useState(0);
  const scanLock = useRef(false);
  const lastScan = useRef<{ value: string; at: number } | null>(null);

  const refreshCount = useCallback(async () => {
    if (!trips.selectedTripId) return;
    const counts = await attendanceQueueCounts(trips.selectedTripId);
    setPending((counts.pending ?? 0) + (counts.sending ?? 0) + (counts.retryable ?? 0));
  }, [trips.selectedTripId]);

  const handleScan = useCallback(async ({ data }: BarcodeScanningResult) => {
    const tripId = trips.selectedTripId;
    if (!tripId || !selectedSession || scanLock.current) return;
    const now = Date.now();
    if (lastScan.current?.value === data && now - lastScan.current.at < 2_000) return;
    lastScan.current = { value: data, at: now };
    scanLock.current = true;
    try {
      if (!validAttendanceQr(data)) {
        setScanState({ tone: 'danger', message: 'This is not a valid Group Companion attendance QR.' });
        return;
      }
      const queued = await enqueueQrScan(tripId, selectedSession.id, data);
      setScanState({
        tone: queued.duplicate ? 'warning' : 'good',
        message: queued.duplicate
          ? 'This scan is already queued and pending server verification.'
          : 'Scan queued securely. Attendance is pending server verification.',
      });
      await refreshCount();
      await drainAttendanceQueue(tripId).catch(() => undefined);
      await refreshCount();
    } catch {
      setScanState({ tone: 'danger', message: 'The scan could not be saved. Please try again.' });
    } finally {
      setTimeout(() => {
        scanLock.current = false;
      }, 900);
    }
  }, [refreshCount, selectedSession, trips.selectedTripId]);

  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader eyebrow="Attendance" title="Scan QR" subtitle="Every scan is durably queued before synchronization." />
      <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
      {!trips.selectedTripId ? <ContentEmpty title="Select a trip" message="Choose an assigned trip before scanning attendance." /> : null}
      {trips.selectedTripId && !selectedSession ? (
        <ContentEmpty
          title="Select an attendance activity"
          message="Open Attendance, create or select an active activity, then return to Scan QR."
        />
      ) : null}
      {selectedSession ? <StatusPill label={`Activity: ${selectedSession.name}`} tone="good" /> : null}
      {trips.selectedTripId && selectedSession && !permission?.granted ? (
        <GlassCard style={styles.permission}>
          <ScanLine color={colors.blueDeep} size={30} />
          <Text style={styles.title}>Camera access is needed</Text>
          <Text style={styles.message}>The camera is used only while you scan an attendance QR.</Text>
          <PrimaryButton label="Allow camera" onPress={() => void requestPermission()} />
        </GlassCard>
      ) : null}
      {trips.selectedTripId && selectedSession && permission?.granted ? (
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
            {torch ? <FlashlightOff color={colors.white} size={22} /> : <Flashlight color={colors.white} size={22} />}
          </Pressable>
        </View>
      ) : null}
      {scanState ? (
        <GlassCard style={[styles.result, scanState.tone === 'danger' && styles.resultDanger]}>
          {scanState.tone === 'good' ? <CheckCircle2 color={colors.greenDeep} size={22} /> : <WifiOff color={scanState.tone === 'danger' ? colors.danger : colors.warning} size={22} />}
          <Text accessibilityLiveRegion="polite" style={styles.resultText}>{scanState.message}</Text>
        </GlassCard>
      ) : null}
      <Text style={styles.queueText}>{pending > 0 ? `${pending} scan${pending === 1 ? '' : 's'} waiting to synchronize` : 'No attendance scans waiting to synchronize'}</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  permission: { gap: spacing.md, alignItems: 'center' },
  title: { color: colors.ink, fontSize: 18, fontWeight: '800' },
  message: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center' },
  cameraFrame: { height: 390, overflow: 'hidden', borderRadius: radii.lg, backgroundColor: colors.ink },
  guide: { position: 'absolute', width: 230, height: 230, alignSelf: 'center', top: 80, borderWidth: 3, borderColor: colors.white, borderRadius: 28 },
  torch: { position: 'absolute', right: spacing.lg, top: spacing.lg, width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center' },
  result: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radii.md },
  resultDanger: { borderColor: 'rgba(184,64,77,0.3)' },
  resultText: { flex: 1, color: colors.ink, fontSize: 14, fontWeight: '700' },
  queueText: { color: colors.inkMuted, textAlign: 'center', fontSize: 12 },
});
