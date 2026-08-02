import HardDrive from 'lucide-react-native/icons/hard-drive';
import LogOut from 'lucide-react-native/icons/log-out';
import ShieldCheck from 'lucide-react-native/icons/shield-check';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { logoutSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { vaultUsageBytes } from '@/core/storage/vault';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { removeOfflineCache } from '@/features/content/data/content-repository';

function storageLabel(bytes: number): string {
  if (bytes < 1024) return '0 KB';
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ProfileScreen({ eyebrow }: { eyebrow: string }) {
  const session = useSessionStore((state) => state.session);
  const [storage, setStorage] = useState(0);
  const [clearing, setClearing] = useState(false);
  const namespace = session
    ? accountNamespace({ agencyId: session.principal.agencyId, principalId: session.principal.id })
    : null;

  useEffect(() => {
    if (namespace) void vaultUsageBytes(namespace).then(setStorage);
  }, [namespace]);

  async function clearDocuments() {
    setClearing(true);
    try {
      await removeOfflineCache();
      setStorage(0);
    } finally {
      setClearing(false);
    }
  }

  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader
        eyebrow={eyebrow}
        title={session?.principal.displayName || 'Profile'}
        subtitle="Privacy, sessions and offline storage on this device."
      />
      <GlassCard style={styles.card}>
        <View style={styles.row}>
          <ShieldCheck color={colors.greenDeep} size={24} />
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Account-isolated storage</Text>
            <Text style={styles.rowDescription}>
              This account has its own encrypted database and document vault. Switching accounts purges the previous account from this device.
            </Text>
          </View>
        </View>
      </GlassCard>
      <GlassCard style={styles.card}>
        <View style={styles.row}>
          <HardDrive color={colors.blueDeep} size={24} />
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Offline files</Text>
            <Text style={styles.rowDescription}>{storageLabel(storage)} in app-private storage</Text>
          </View>
        </View>
        <PrimaryButton
          label="Remove offline documents"
          tone="secondary"
          loading={clearing}
          onPress={() => void clearDocuments()}
        />
      </GlassCard>
      <GlassCard style={styles.card}>
        <View style={styles.row}>
          <LogOut color={colors.danger} size={24} />
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Sign out</Text>
            <Text style={styles.rowDescription}>
              Your encrypted database, queued actions and offline files are removed locally even if the server is temporarily unreachable.
            </Text>
          </View>
        </View>
        <PrimaryButton label="Sign out and clear device" tone="danger" onPress={() => void logoutSession()} />
      </GlassCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  card: { borderRadius: radii.md, gap: spacing.lg },
  row: { flexDirection: 'row', gap: spacing.md },
  rowText: { flex: 1, gap: spacing.xs },
  rowTitle: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  rowDescription: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
