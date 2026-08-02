import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import Bell from 'lucide-react-native/icons/bell';
import CircleAlert from 'lucide-react-native/icons/circle-alert';
import { useCallback, useMemo } from 'react';
import {
  Pressable,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import type { Announcement } from '@/features/content/api/content-contracts';
import { useAnnouncements } from '@/features/content/hooks/use-content';
import type { MobileNotification } from '@/features/notifications/api/notification-contracts';
import { useNotifications } from '@/features/notifications/hooks/use-notifications';
import { useTrips } from '@/features/trips/hooks/use-trips';

type Row =
  | { kind: 'notification'; value: MobileNotification }
  | { kind: 'announcement'; value: Announcement };
type UpdatesSection = { title: 'Updates' | 'Group announcements'; data: Row[] };

export default function PassengerUpdatesScreen() {
  const trips = useTrips();
  const notifications = useNotifications(trips.selectedTripId);
  const announcements = useAnnouncements(trips.selectedTripId);
  const notificationItems = useMemo(() => {
    const unique = new Map<string, MobileNotification>();
    for (const item of notifications.data?.pages.flatMap((page) => page.items) ?? []) {
      if (!unique.has(item.id)) unique.set(item.id, item);
    }
    return [...unique.values()];
  }, [notifications.data]);
  const unread = notifications.data?.pages[0]?.unread_count ?? 0;
  const offline = notifications.data?.pages.some((page) => page.offline) || announcements.data?.offline;
  const sections = useMemo<UpdatesSection[]>(() => {
    const values: UpdatesSection[] = [];
    if (notificationItems.length) {
      values.push({
        title: 'Updates',
        data: notificationItems.map((item) => ({ kind: 'notification', value: item })),
      });
    }
    if (announcements.data?.items.length) {
      values.push({
        title: 'Group announcements',
        data: announcements.data.items.map((item) => ({ kind: 'announcement', value: item })),
      });
    }
    return values;
  }, [announcements.data, notificationItems]);

  const renderItem = useCallback(({ item }: SectionListRenderItemInfo<Row, UpdatesSection>) => {
    if (item.kind === 'announcement') {
      const announcement = item.value;
      return (
        <GlassCard style={[styles.card, announcement.priority === 'emergency' && styles.emergency]}>
          <Text style={styles.title}>{announcement.title}</Text>
          <Text style={styles.date}>{new Date(announcement.published_at).toLocaleString()}</Text>
          <Text style={styles.message}>{announcement.message}</Text>
        </GlassCard>
      );
    }
    const notification = item.value;
    const Icon = notification.priority === 'emergency' ? CircleAlert : notification.priority === 'important' ? AlertTriangle : Bell;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${notification.read_at ? 'Read' : 'Unread'} update: ${notification.title}`}
        onPress={() => notifications.markRead(notification.id)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.card, notification.priority === 'emergency' && styles.emergency, !notification.read_at && styles.unread]}>
          <View style={styles.heading}>
            <View style={[styles.icon, notification.priority !== 'normal' && styles.importantIcon]}>
              <Icon color={notification.priority === 'normal' ? colors.blueDeep : colors.danger} size={20} />
            </View>
            <View style={styles.headingText}>
              <Text style={styles.title}>{notification.title}</Text>
              <Text style={styles.date}>{notification.category} · {new Date(notification.available_at).toLocaleString()}</Text>
            </View>
            {!notification.read_at ? <View accessibilityLabel="Unread" style={styles.unreadDot} /> : null}
          </View>
          <Text style={styles.message}>{notification.body}</Text>
        </GlassCard>
      </Pressable>
    );
  }, [notifications]);

  const loadMore = useCallback(() => {
    if (notifications.hasNextPage && !notifications.isFetchingNextPage) void notifications.fetchNextPage();
  }, [notifications]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<Row, UpdatesSection>
        sections={sections}
        renderItem={renderItem}
        renderSectionHeader={({ section }) => (
          <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
        )}
        keyExtractor={(item) => `${item.kind}:${item.value.id}`}
        stickySectionHeadersEnabled={false}
        initialNumToRender={10}
        maxToRenderPerBatch={14}
        windowSize={7}
        onEndReached={loadMore}
        onEndReachedThreshold={0.6}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={ListSeparator}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader
              eyebrow="Latest"
              title="Updates"
              subtitle="Trip changes, document availability and operational alerts."
              accessory={unread > 0 ? <StatusPill label={`${unread} unread`} tone="warning" /> : undefined}
            />
            {offline ? <StatusPill label="Last synchronized updates" tone="warning" /> : null}
            {notifications.isPending && announcements.isPending ? <ContentLoading label="Loading updates" /> : null}
            {notifications.isError && announcements.isError ? (
              <ContentError message="Updates have not been synchronized on this device." onRetry={() => { void notifications.refetch(); void announcements.refetch(); }} />
            ) : null}
          </View>
        }
        ListEmptyComponent={
          !notifications.isPending && !announcements.isPending ? (
            <ContentEmpty title="You are up to date" message="Published changes, announcements and personal alerts will appear here." />
          ) : null
        }
        ListFooterComponent={
          notifications.hasNextPage ? (
            <View style={styles.footer}>
              <PrimaryButton label="Load older updates" tone="secondary" loading={notifications.isFetchingNextPage} onPress={loadMore} />
            </View>
          ) : null
        }
      />
    </Screen>
  );
}

function ListSeparator() {
  return <View style={styles.separator} />;
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { flexGrow: 1, paddingHorizontal: spacing.lg, paddingBottom: 104 },
  header: { gap: spacing.lg, paddingBottom: spacing.md },
  footer: { paddingTop: spacing.lg },
  separator: { height: spacing.sm },
  sectionTitle: { color: colors.ink, fontSize: 19, fontWeight: '900', paddingTop: spacing.lg, paddingBottom: spacing.sm, backgroundColor: 'rgba(248,253,255,0.97)' },
  card: { borderRadius: radii.md, gap: spacing.md },
  emergency: { borderColor: 'rgba(184,64,77,0.32)', backgroundColor: 'rgba(255,244,244,0.9)' },
  unread: { borderColor: colors.blue },
  heading: { flexDirection: 'row', gap: spacing.md, alignItems: 'center' },
  icon: { width: 38, height: 38, borderRadius: 13, backgroundColor: colors.blueSoft, alignItems: 'center', justifyContent: 'center' },
  importantIcon: { backgroundColor: '#FFE8E8' },
  headingText: { flex: 1, gap: 2 },
  title: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  date: { color: colors.inkMuted, fontSize: 11, textTransform: 'capitalize' },
  message: { color: colors.inkMuted, fontSize: 14, lineHeight: 21 },
  unreadDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: colors.blue },
  pressed: { opacity: 0.7 },
});
