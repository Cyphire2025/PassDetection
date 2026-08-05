import { useNetInfo } from '@react-native-community/netinfo';
import WifiOff from 'lucide-react-native/icons/wifi-off';
import { StyleSheet, Text, View } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { colors, radii, spacing } from '@/design/theme';

export function OfflineStatusChip() {
  const sessionMode = useSessionStore((state) => state.session?.networkMode ?? null);
  const network = useNetInfo();
  const isOffline = sessionMode === 'offline'
    || network.isConnected === false
    || network.isInternetReachable === false;

  if (!isOffline) return null;

  return (
    <View accessibilityRole="text" style={styles.root}>
      <WifiOff color={colors.blueSoft} size={13} />
      <Text numberOfLines={1} style={styles.label}>Offline — using saved trip data</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    maxWidth: 218,
    minHeight: 28,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: 'rgba(221,243,252,0.28)',
    backgroundColor: 'rgba(8,41,54,0.5)',
    paddingHorizontal: spacing.sm,
  },
  label: { flexShrink: 1, color: colors.white, fontSize: 10, fontWeight: '700' },
});
