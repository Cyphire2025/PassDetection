import DownloadCloud from 'lucide-react-native/icons/cloud-download';
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { colors, radii, spacing } from '@/design/theme';

import { Screen } from './screen';

type RequiredDownloadScreenProps = {
  title?: string;
  message: string;
  progress: number;
  completedLabel?: string;
  error?: string | null;
  onRetry?: () => void;
  errorSecondaryAction?: ReactNode;
};

export function RequiredDownloadScreen({
  title,
  message,
  progress,
  completedLabel,
  error,
  onRetry,
  errorSecondaryAction,
}: RequiredDownloadScreenProps) {
  const messages = useMessages();
  const normalizedProgress = Math.max(0, Math.min(100, Math.round(progress)));
  const resolvedTitle = title ?? messages.downloadingRequiredDocuments();
  return (
    <Screen contentStyle={styles.screen}>
      <View style={styles.content}>
        <View style={styles.icon} accessibilityElementsHidden>
          <DownloadCloud color={colors.greenDeep} size={34} strokeWidth={2.2} />
        </View>
        <View style={styles.copy}>
          <Text accessibilityRole="header" style={styles.title}>{resolvedTitle}</Text>
          <Text style={styles.message}>{error ?? message}</Text>
        </View>
        {error ? (
          <View style={styles.errorActions}>
            <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
              <Text style={styles.retryText}>{messages.tryAgain()}</Text>
            </Pressable>
            {errorSecondaryAction}
          </View>
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
              <Text style={styles.progressText}>{completedLabel ?? messages.preparingOfflineAccess()}</Text>
              <Text style={styles.percent}>{normalizedProgress}%</Text>
            </View>
          </View>
        )}
        {!error ? <ActivityIndicator color={colors.greenDeep} size="small" /> : null}
        <Text style={styles.note}>{messages.secureDownloadPrivacyNote()}</Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { flexGrow: 1, justifyContent: 'center' },
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
  errorActions: { width: '100%', maxWidth: 380, gap: spacing.md },
  retryText: { color: colors.ink, fontSize: 16, fontWeight: '900' },
  note: { maxWidth: 340, color: colors.inkMuted, fontSize: 12, lineHeight: 18, textAlign: 'center' },
});
