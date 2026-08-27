import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import ImageIcon from 'lucide-react-native/icons/image';
import Trash2 from 'lucide-react-native/icons/trash-2';
import { useCallback } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { formatInstantDateTime } from '@/core/localization/date-time';
import { useMessages } from '@/core/localization/localization-provider';
import type { IanaTimeZone } from '@/core/localization/time-zone';
import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';

import type {
  CompletedPhotoDownloadPage,
  PhotoDownloadJob,
} from '../downloads/download-repository';
import { formatPrivatePhotoBytes } from './format-private-bytes';

type Props = Readonly<{
  page: CompletedPhotoDownloadPage | null;
  loading: boolean;
  error: boolean;
  removingJobId: string | null;
  timeZone?: IanaTimeZone;
  onNext: () => void;
  onOpen: (job: PhotoDownloadJob) => void;
  onPrevious: () => void;
  onRemove: (job: PhotoDownloadJob) => void;
  onRetry: () => void;
}>;

export function DownloadedPhotosCard({
  page,
  loading,
  error,
  removingJobId,
  timeZone,
  onNext,
  onOpen,
  onPrevious,
  onRemove,
  onRetry,
}: Props) {
  const messages = useMessages();
  const renderJob = useCallback((job: PhotoDownloadJob, index: number) => {
    const quality = job.quality === 'original'
      ? messages.myPhotosOriginalQuality()
      : messages.myPhotosOptimizedQuality();
    const downloaded = job.completedAt && Number.isFinite(Date.parse(job.completedAt))
      ? messages.myPhotosDownloadedOn(formatInstantDateTime(job.completedAt, { timeZone }))
      : messages.myPhotosDownloadCompleted();
    const size = job.encryptedSizeBytes === null
      ? null
      : formatPrivatePhotoBytes(job.encryptedSizeBytes);
    const removing = removingJobId === job.id;
    return (
      <View key={job.id} style={styles.row}>
        <Pressable
          accessibilityHint={messages.myPhotosAvailableOffline()}
          accessibilityLabel={`${messages.myPhotosDownloadedPhoto(index + 1)}. ${quality}. ${downloaded}.`}
          accessibilityRole="button"
          disabled={removing}
          onPress={() => onOpen(job)}
          style={styles.open}>
          <View style={styles.icon}>
            <ImageIcon color={colors.greenDeep} size={20} />
          </View>
          <View style={styles.copy}>
            <Text numberOfLines={1} style={styles.photoTitle}>{messages.myPhotosDownloadedPhoto(index + 1)}</Text>
            <Text numberOfLines={1} style={styles.meta}>{[quality, size].filter(Boolean).join(' - ')}</Text>
            <Text numberOfLines={1} style={styles.meta}>{downloaded}</Text>
          </View>
          <ChevronRight color={colors.inkMuted} size={19} />
        </Pressable>
        <Pressable
          accessibilityLabel={messages.myPhotosRemoveDownloadedPhoto()}
          accessibilityRole="button"
          disabled={removing}
          onPress={() => onRemove(job)}
          style={styles.remove}>
          {removing
            ? <ActivityIndicator color={colors.danger} size="small" />
            : <Trash2 color={colors.danger} size={18} />}
        </Pressable>
      </View>
    );
  }, [messages, onOpen, onRemove, removingJobId, timeZone]);

  return (
    <GlassCard accessibilityLabel={messages.myPhotosDownloadedPhotos()} style={styles.card}>
      <View style={styles.heading}>
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosDownloadedPhotos()}</Text>
        <Text style={styles.explanation}>{messages.myPhotosDownloadedPhotosExplanation()}</Text>
      </View>
      {loading ? (
        <View accessibilityLabel={messages.loading()} accessibilityRole="progressbar" style={styles.state}>
          <ActivityIndicator color={colors.greenDeep} />
        </View>
      ) : error ? (
        <Pressable accessibilityRole="button" onPress={onRetry} style={styles.stateButton}>
          <Text style={styles.retry}>{messages.tryAgain()}</Text>
        </Pressable>
      ) : !page?.items.length ? (
        <View style={styles.state}>
          <Text style={styles.emptyTitle}>{messages.myPhotosNoDownloadedPhotos()}</Text>
          <Text style={styles.explanation}>{messages.myPhotosNoDownloadedPhotosMessage()}</Text>
        </View>
      ) : (
        <View style={styles.rows}>{page.items.map(renderJob)}</View>
      )}
      {page?.previousCursor || page?.nextCursor ? (
        <View style={styles.pagination}>
          <Pressable
            accessibilityLabel={messages.myPhotosPreviousDownloads()}
            accessibilityRole="button"
            disabled={!page.previousCursor || loading}
            onPress={onPrevious}
            style={[styles.pageButton, (!page.previousCursor || loading) && styles.disabled]}>
            <ChevronLeft color={colors.greenDeep} size={18} />
            <Text style={styles.pageText}>{messages.myPhotosPreviousDownloads()}</Text>
          </Pressable>
          <Pressable
            accessibilityLabel={messages.myPhotosNextDownloads()}
            accessibilityRole="button"
            disabled={!page.nextCursor || loading}
            onPress={onNext}
            style={[styles.pageButton, (!page.nextCursor || loading) && styles.disabled]}>
            <Text style={styles.pageText}>{messages.myPhotosNextDownloads()}</Text>
            <ChevronRight color={colors.greenDeep} size={18} />
          </Pressable>
        </View>
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  heading: { gap: spacing.xs },
  title: { color: colors.ink, fontSize: 18, fontWeight: '900' },
  explanation: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  rows: { gap: spacing.sm },
  row: { minHeight: 72, flexDirection: 'row', alignItems: 'stretch', borderRadius: radii.md, backgroundColor: colors.aquaSoft, overflow: 'hidden' },
  open: { minHeight: 72, flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm },
  icon: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 20, backgroundColor: colors.white },
  copy: { flex: 1, gap: 2 },
  photoTitle: { color: colors.ink, fontSize: 13, fontWeight: '900' },
  meta: { color: colors.inkMuted, fontSize: 11, lineHeight: 15 },
  remove: { width: 48, minHeight: 48, alignItems: 'center', justifyContent: 'center', borderLeftWidth: 1, borderLeftColor: colors.border },
  state: { minHeight: 72, alignItems: 'center', justifyContent: 'center', gap: spacing.xs },
  stateButton: { minHeight: 48, alignItems: 'center', justifyContent: 'center' },
  emptyTitle: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  retry: { color: colors.greenDeep, fontSize: 13, fontWeight: '900' },
  pagination: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm },
  pageButton: { minHeight: 48, flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs, borderRadius: radii.pill, borderWidth: 1, borderColor: colors.greenDeep, paddingHorizontal: spacing.sm },
  pageText: { flexShrink: 1, color: colors.greenDeep, fontSize: 11, fontWeight: '900', textAlign: 'center' },
  disabled: { opacity: 0.4 },
});
