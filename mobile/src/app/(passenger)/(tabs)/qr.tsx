import * as Brightness from 'expo-brightness';
import * as ScreenCapture from 'expo-screen-capture';
import { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';
import { useQr } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';

export default function PassengerQrScreen() {
  const trips = useTrips();
  const qr = useQr(trips.selectedTripId);
  ScreenCapture.usePreventScreenCapture('passenger-personal-qr');

  useEffect(() => {
    let active = true;
    let previous: number | null = null;
    void Brightness.isAvailableAsync().then(async (available) => {
      if (!available || !active) return;
      previous = await Brightness.getBrightnessAsync();
      if (!active) return;
      await Brightness.setBrightnessAsync(1);
    }).catch(() => undefined);
    return () => {
      active = false;
      if (previous !== null) void Brightness.setBrightnessAsync(previous);
    };
  }, []);

  return (
    <Screen scroll={false} bottomInset={104} contentStyle={styles.screen}>
      <PageHeader eyebrow="Attendance" title="My QR" subtitle={trips.selectedTrip?.name || 'Passenger-specific trip QR'} />
      {qr.isPending ? <ContentLoading label="Preparing your QR" /> : null}
      {qr.isError ? <ContentError message="Your QR is not available offline yet." onRetry={() => void qr.refetch()} /> : null}
      {qr.data?.qr ? (
        <GlassCard style={styles.qrCard}>
          <View style={styles.qrSurface}>
            <QRCode value={qr.data.qr.signed_payload} size={244} color="#000000" backgroundColor="#FFFFFF" ecl="H" />
          </View>
          <Text style={styles.name}>{trips.selectedTrip?.destination || trips.selectedTrip?.name}</Text>
          <Text style={styles.ready}>Ready for your checkpoint · available offline</Text>
          <Text style={styles.help}>Show this screen at your group checkpoint. It is bound to you and this trip.</Text>
        </GlassCard>
      ) : null}
      <Text style={styles.brightness}>Screen brightness is raised only while this page is open and restored when you leave.</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  qrCard: { alignItems: 'center', justifyContent: 'center', gap: spacing.md, paddingVertical: spacing.xl },
  qrSurface: { backgroundColor: colors.white, padding: spacing.md, borderRadius: 18 },
  name: { color: colors.ink, fontSize: 20, fontWeight: '800', textAlign: 'center' },
  ready: { color: colors.greenDeep, fontSize: 13, fontWeight: '800', textAlign: 'center' },
  help: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center', maxWidth: 300 },
  brightness: { color: colors.inkMuted, fontSize: 12, lineHeight: 18, textAlign: 'center' },
});
