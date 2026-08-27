import Clock3 from 'lucide-react-native/icons/clock-3';
import Download from 'lucide-react-native/icons/download';
import HardDrive from 'lucide-react-native/icons/hard-drive';
import Sparkles from 'lucide-react-native/icons/sparkles';
import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { formatInstantDateTime } from '@/core/localization/date-time';
import { useMessages } from '@/core/localization/localization-provider';
import type { IanaTimeZone } from '@/core/localization/time-zone';
import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';

import type { MyPhotosSummary } from '../api/contracts';

type Props = Readonly<{
  summary: MyPhotosSummary;
  downloadedCount: number;
  storageUsedLabel: string;
  timeZone?: IanaTimeZone;
}>;

function Stat({ icon, label }: Readonly<{ icon: ReactNode; label: string }>) {
  return (
    <View style={styles.stat}>
      {icon}
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

export function MyPhotosOverview({ summary, downloadedCount, storageUsedLabel, timeZone }: Props) {
  const messages = useMessages();
  return (
    <GlassCard style={styles.card}>
      <Text accessibilityRole="header" style={styles.count}>{messages.myPhotosPhotosFound(summary.results.match_count)}</Text>
      {summary.results.new_photo_count > 0 ? (
        <View style={styles.newBadge}>
          <Sparkles color={colors.greenDeep} size={15} />
          <Text style={styles.newText}>{messages.myPhotosNewPhotos(summary.results.new_photo_count)}</Text>
        </View>
      ) : null}
      <View style={styles.stats}>
        <Stat icon={<Download color={colors.blueDeep} size={17} />} label={messages.myPhotosDownloaded(downloadedCount)} />
        <Stat icon={<HardDrive color={colors.blueDeep} size={17} />} label={messages.myPhotosStorageUsed(storageUsedLabel)} />
        {summary.results.last_updated_at ? (
          <Stat
            icon={<Clock3 color={colors.blueDeep} size={17} />}
            label={messages.myPhotosLastUpdated(formatInstantDateTime(
              summary.results.last_updated_at,
              { timeZone: timeZone ?? undefined },
            ))}
          />
        ) : null}
      </View>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  count: { color: colors.ink, fontSize: 26, lineHeight: 32, fontWeight: '900' },
  newBadge: { alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: spacing.xs, borderRadius: radii.pill, backgroundColor: colors.greenSoft, paddingHorizontal: spacing.sm, paddingVertical: 5 },
  newText: { color: colors.greenDeep, fontSize: 12, fontWeight: '900' },
  stats: { gap: spacing.sm },
  stat: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  statLabel: { flex: 1, color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
