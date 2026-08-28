import ScanLine from 'lucide-react-native/icons/scan-line';
import { Linking, StyleSheet, Text } from 'react-native';

import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

type Props = Readonly<{
  canAskAgain: boolean;
  onRequestPermission: () => Promise<unknown>;
}>;

export function CameraPermissionCard({ canAskAgain, onRequestPermission }: Props) {
  return (
    <GlassCard style={styles.card}>
      <ScanLine color={colors.greenDeep} size={30} />
      <Text style={styles.title}>Camera access is needed</Text>
      <Text style={styles.message}>
        {canAskAgain
          ? 'The camera is used only while scanning attendance QR codes.'
          : 'Enable Camera in your phone settings to scan attendance QR codes.'}
      </Text>
      <PrimaryButton
        label={canAskAgain ? 'Allow camera' : 'Open app settings'}
        onPress={() => void (canAskAgain ? onRequestPermission() : Linking.openSettings())}
      />
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, alignItems: 'center' },
  title: { color: colors.ink, fontSize: 18, fontWeight: '800' },
  message: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center' },
});
