import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { demoRoster, markDemoAttendance } from '@/core/demo/demo-operations';
import { useRouteFocus } from '@/core/query/use-route-focus';
import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';
import { useCoordinatorTrips } from '../hooks/use-coordinator-trips';
import { OperationHeader } from './operation-header';

export function DemoScanScreen() {
  const trips = useCoordinatorTrips();
  const focused = useRouteFocus();
  const client = useQueryClient();
  const [permission, requestPermission] = useCameraPermissions();
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const busy = useRef(false);
  const tripId = trips.selectedTripId;
  const roster = useQuery({ queryKey: ['demo-scan-roster', tripId], queryFn: () => demoRoster(tripId!), enabled: Boolean(tripId) });

  async function scan(passengerId: string) {
    if (!tripId || busy.current) return;
    busy.current = true;
    try {
      setNotice(await markDemoAttendance(tripId, passengerId));
      await client.invalidateQueries();
    } catch {
      setNotice('Use a sample QR from this demo. Real trip QRs are not accepted.');
    } finally { busy.current = false; }
  }

  return <Screen contentStyle={styles.screen}>
    <OperationHeader title="Demo attendance scan" subtitle={trips.selectedTrip?.name ?? 'Choose a sample group first'} />
    <GlassCard style={styles.card}>
      <Text style={styles.copy}>Attendance changes are saved only on this device. Scan a sample QR, or use a sample scan below to test without a second phone.</Text>
      {permission?.granted && focused ? <CameraView style={styles.camera} barcodeScannerSettings={{ barcodeTypes: ['qr'] }} onBarcodeScanned={({ data }) => {
        const match = /^GC-DEMO:([0-9a-f-]{36})$/.exec(data);
        if (match) void scan(match[1]!);
        else setNotice('This demo accepts only the sample QRs shown below.');
      }} /> : <PrimaryButton label="Enable camera for sample QR scanning" tone="secondary" onPress={() => { void requestPermission(); }} />}
      {notice ? <Text accessibilityRole="alert" style={styles.notice}>{notice}</Text> : null}
    </GlassCard>
    {roster.isLoading ? <ContentLoading /> : null}
    {roster.isError ? <ContentError message="The sample roster could not be loaded." onRetry={() => { void roster.refetch(); }} /> : null}
    {(roster.data ?? []).map((passenger) => <GlassCard key={passenger.id} style={styles.card}>
      <Text style={styles.name}>{passenger.display_name}</Text>
      <Text style={styles.copy}>{passenger.employee_code} · {passenger.attendance_status.replace('_', ' ')}</Text>
      <PrimaryButton label={`Sample scan: ${passenger.display_name}`} tone="secondary" onPress={() => { void scan(passenger.id); }} />
      <PrimaryButton label={`Show sample QR: ${passenger.display_name}`} tone="secondary" onPress={() => setSelected(selected === passenger.id ? null : passenger.id)} />
      {selected === passenger.id ? <View style={styles.qr}><QRCode value={`GC-DEMO:${passenger.id}`} size={180} /></View> : null}
    </GlassCard>)}
  </Screen>;
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg }, card: { gap: spacing.md },
  copy: { color: colors.inkMuted, fontSize: 14, lineHeight: 21 },
  name: { color: colors.ink, fontSize: 17, fontWeight: '700' },
  notice: { color: colors.greenDeep, fontSize: 14, lineHeight: 21 },
  camera: { width: '100%', height: 240, borderRadius: 16 },
  qr: { alignItems: 'center', padding: spacing.md, backgroundColor: '#FFFFFF' },
});
