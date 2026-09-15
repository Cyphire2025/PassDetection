import { Redirect, useRouter } from 'expo-router';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { LoadingScreen } from '@/design/components/loading-screen';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, spacing } from '@/design/theme';
import { usePhoneAlerts } from '@/features/notifications/hooks/use-phone-alerts';

export default function PhoneAlertsScreen() {
  const status = useSessionStore((state) => state.status);
  const session = useSessionStore((state) => state.session);
  if (status === 'booting') return <LoadingScreen label="Securing your alerts" />;
  if (!session) return <Redirect href="/(auth)/welcome" />;
  return <AuthenticatedPhoneAlerts />;
}

function AuthenticatedPhoneAlerts() {
  const router = useRouter();
  const alerts = usePhoneAlerts();
  return (
    <Screen scroll={false}>
      <FlatList data={alerts.items} keyExtractor={(item) => item.id} {...MOBILE_LIST_WINDOWING.feed}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={alerts.isRefetching}
          onRefresh={() => { if (alerts.online) void alerts.refetch(); }} />}
        ListHeaderComponent={<View style={styles.header}>
          <PrimaryButton label="Back" tone="secondary" onPress={() => {
            if (router.canGoBack()) router.back(); else router.replace('/');
          }} />
          <PageHeader title="Phone alerts" subtitle="Messages sent to you by your travel team." />
          {!alerts.online ? <StatusPill label="Connect to refresh phone alerts" tone="warning" /> : null}
          {alerts.online && alerts.isPending ? <ContentLoading label="Loading phone alerts" /> : null}
          {alerts.isError ? <ContentError message="Phone alerts could not be loaded. Your trip Updates remain available."
            onRetry={() => { void alerts.refetch(); }} /> : null}
          {alerts.readFailed ? <Text accessibilityRole="alert">Could not mark this alert as read. Tap it again when connected.</Text> : null}
        </View>}
        renderItem={({ item }) => <Pressable accessibilityRole="button"
          accessibilityLabel={`${item.read_at ? 'Read' : 'Unread'} phone alert: ${item.title}`}
          disabled={!alerts.online || alerts.markingRead || Boolean(item.read_at)}
          onPress={() => alerts.markRead(item.id)}>
          <GlassCard style={[styles.card, item.priority === 'emergency' && styles.emergency]}>
            <View style={styles.heading}><StatusPill label={item.priority} tone={item.priority === 'normal' ? 'neutral' : 'warning'} />
              {!item.read_at ? <Text style={styles.unread}>Unread</Text> : null}</View>
            <Text style={styles.title}>{item.title}</Text>
            <Text style={styles.body}>{item.body}</Text>
          </GlassCard>
        </Pressable>}
        ListEmptyComponent={!alerts.isPending && !alerts.isError
          ? <ContentEmpty title="No phone alerts" message="Messages from your travel team will appear here." /> : null}
        ListFooterComponent={alerts.hasNextPage ? <PrimaryButton label="Load older alerts" tone="secondary"
          disabled={!alerts.online} loading={alerts.isFetchingNextPage} onPress={() => { void alerts.fetchNextPage(); }} /> : null}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  list: { gap: spacing.md, paddingBottom: spacing.xl },
  header: { gap: spacing.md, paddingBottom: spacing.md },
  card: { gap: spacing.sm },
  emergency: { borderColor: colors.danger },
  heading: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  body: { color: colors.inkMuted, fontSize: 14, lineHeight: 22 },
  unread: { color: colors.blueDeep, fontWeight: '700' },
});
