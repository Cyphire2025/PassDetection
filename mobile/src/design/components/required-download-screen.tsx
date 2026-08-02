import DownloadCloud from 'lucide-react-native/icons/cloud-download';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

import { Screen } from './screen';

type RequiredDownloadScreenProps = {
  title?: string;
  message: string;
  progress: number;
  completedLabel?: string;
  error?: string | null;
  onRetry?: () => void;
};

export function RequiredDownloadScreen({
  title = 'Downloading required documents',
  message,
  progress,
  completedLabel,
  error,
  onRetry,
}: RequiredDownloadScreenProps) {
  const normalizedProgress = Math.max(0, Math.min(100, Math.round(progress)));
  return (
    <Screen scroll={false} contentStyle={styles.screen}>
      <View style={styles.content}>
        <View style={styles.icon} accessibilityElementsHidden>
          <DownloadCloud color={colors.greenDeep} size={34} strokeWidth={2.2} />
        </View>
        <View style={styles.copy}>
          <Text accessibilityRole="header" style={styles.title}>{title}</Text>
          <Text style={styles.message}>{error ?? message}</Text>
        </View>
        {error ? (
          <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        ) : (
          <View style={styles.progressGroup}>
            <View
              accessibilityRole="progressbar"
              accessibilityLabel={message}
              accessibilityValue={{ min: 0, max: 100, now: normalizedProgress }}
              style={styles.track}>
              <View style={[styles.fill, { width: `${normalizedProgress}%` }]} />
            </View>
            <View style={styles.progressLabels}>
              <Text style={styles.progressText}>{completedLabel ?? 'Preparing offline access'}</Text>
              <Text style={styles.percent}>{normalizedProgress}%</Text>
            </View>
          </View>
        )}
        {!error ? <ActivityIndicator color={colors.greenDeep} size="small" /> : null}
        <Text style={styles.note}>Keep the app open. Encrypted copies stay private to this account and device.</Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { justifyContent: 'center' },
  content: { gap: spacing.xl, alignItems: 'center' },
  icon: {
    width: 76,
    height: 76,
    borderRadius: 25,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
    borderWidth: 1,
    borderColor: colors.border,
  },
  copy: { gap: spacing.sm, alignItems: 'center', maxWidth: 360 },
  title: { color: colors.ink, fontSize: 28, lineHeight: 34, fontWeight: '900', textAlign: 'center' },
  message: { color: colors.inkMuted, fontSize: 15, lineHeight: 22, textAlign: 'center' },
  progressGroup: { width: '100%', maxWidth: 380, gap: spacing.sm },
  track: { height: 12, overflow: 'hidden', borderRadius: radii.pill, backgroundColor: colors.border },
  fill: { height: '100%', borderRadius: radii.pill, backgroundColor: colors.green },
  progressLabels: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
  progressText: { flex: 1, color: colors.inkMuted, fontSize: 12 },
  percent: { color: colors.greenDeep, fontSize: 12, fontWeight: '900' },
  retry: {
    minWidth: 160,
    minHeight: 50,
    paddingHorizontal: spacing.xl,
    borderRadius: radii.pill,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.green,
  },
  retryText: { color: colors.ink, fontSize: 16, fontWeight: '900' },
  note: { maxWidth: 340, color: colors.inkMuted, fontSize: 12, lineHeight: 18, textAlign: 'center' },
});
