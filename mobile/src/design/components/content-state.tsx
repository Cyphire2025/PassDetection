import RefreshCw from 'lucide-react-native/icons/refresh-cw';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { colors, spacing } from '@/design/theme';

export function ContentLoading({ label }: { label?: string }) {
  const messages = useMessages();
  const resolvedLabel = label ?? messages.loading();
  return (
    <View accessibilityRole="progressbar" accessibilityLabel={resolvedLabel} style={styles.state}>
      <ActivityIndicator color={colors.greenDeep} />
      <Text style={styles.text}>{resolvedLabel}</Text>
    </View>
  );
}

export function ContentError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const messages = useMessages();
  return (
    <View style={styles.state}>
      <Text accessibilityRole="alert" style={styles.error}>
        {message}
      </Text>
      {onRetry ? (
        <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
          <RefreshCw color={colors.greenDeep} size={17} />
          <Text style={styles.retryText}>{messages.tryAgain()}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function ContentEmpty({ title, message }: { title: string; message: string }) {
  return (
    <View style={styles.state}>
      <Text accessibilityRole="header" style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  state: { paddingVertical: spacing.xl, alignItems: 'center', gap: spacing.sm },
  text: { color: colors.inkMuted, fontSize: 14, lineHeight: 20, textAlign: 'center' },
  error: { color: colors.danger, fontSize: 14, lineHeight: 20, textAlign: 'center' },
  retry: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  retryText: { color: colors.greenDeep, fontWeight: '700' },
  emptyTitle: { color: colors.ink, fontSize: 17, fontWeight: '800' },
});
