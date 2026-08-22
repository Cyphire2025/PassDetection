import { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { useRealtimeStatusStore } from '@/core/realtime/realtime-status';
import { requestSync } from '@/core/sync/sync-trigger';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

type Props = Readonly<{
  onSynchronized: () => Promise<unknown>;
  tripId: string;
}>;

export function ScanConnectivityCard({ onSynchronized, tripId }: Props) {
  const realtimeStatus = useRealtimeStatusStore((state) => state.status);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const connected = realtimeStatus === 'connected';

  const synchronizeNow = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      await requestSync({ scope: 'trip', tripId, reason: 'manual-realtime-degraded' });
      await onSynchronized();
      setMessage('Latest attendance data synchronized.');
    } catch (caught) {
      setMessage(userFacingErrorMessage(
        caught,
        'Synchronization is unavailable; scans still save locally.',
      ));
    } finally {
      setBusy(false);
    }
  }, [busy, onSynchronized, tripId]);

  return (
    <GlassCard style={connected ? styles.healthy : styles.degraded}>
      <View style={styles.copy}>
        <Text style={styles.title}>
          {connected ? 'Live updates connected' : 'Live updates delayed'}
        </Text>
        <Text style={styles.message}>
          {connected
            ? 'Dashboard and device changes trigger an immediate authoritative refresh.'
            : 'Scans still save securely on this device. Use Sync now when a connection is available.'}
        </Text>
        {message ? <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text> : null}
      </View>
      {!connected ? (
        <PrimaryButton
          testID="scan-manual-sync"
          label="Sync now"
          loading={busy}
          tone="secondary"
          onPress={() => void synchronizeNow()}
        />
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  healthy: { gap: spacing.sm, borderColor: colors.green, borderWidth: 1 },
  degraded: { gap: spacing.md, borderColor: colors.warning, borderWidth: 1 },
  copy: { gap: spacing.xs },
  title: { color: colors.ink, fontSize: 15, fontWeight: '900' },
  message: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
});
