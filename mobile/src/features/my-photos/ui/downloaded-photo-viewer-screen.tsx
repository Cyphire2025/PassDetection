import { router, useLocalSearchParams } from 'expo-router';
import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import Share2 from 'lucide-react-native/icons/share-2';
import Trash2 from 'lucide-react-native/icons/trash-2';
import { useCallback } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import { ContentError, ContentLoading } from '@/design/components/content-state';
import { colors, radii, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

import type { DownloadQuality } from '../api/contracts';
import {
  useOwnedPhotoDownload,
  usePhotoDownloads,
} from '../hooks/use-photo-downloads';
import { formatPrivatePhotoBytes } from './format-private-bytes';
import { photoDownloadStatusCopy } from './photo-download-status-copy';
import { sharePrivatePhoto } from './share-private-photo';
import { usePrivatePhotoView } from './use-private-photo-view';
import { ZoomablePhoto } from './zoomable-photo';

export function DownloadedPhotoViewerScreen() {
  const messages = useMessages();
  const params = useLocalSearchParams<{ jobId?: string | string[] }>();
  const jobId = typeof params.jobId === 'string' ? params.jobId : params.jobId?.[0] ?? null;
  const trips = useTrips();
  const tripId = trips.selectedTripId;
  const jobQuery = useOwnedPhotoDownload(tripId, jobId);
  const downloads = usePhotoDownloads(tripId);
  const {
    openLocal,
    remove,
    resume,
  } = downloads;
  const job = jobQuery.data ?? null;
  const openExactLocal = useCallback((
    assetId: string,
    _requestedQuality: DownloadQuality,
    signal?: AbortSignal,
  ) => (
    job ? openLocal(assetId, job.quality, signal) : Promise.resolve(null)
  ), [job, openLocal]);
  const localView = usePrivatePhotoView(
    job?.state === 'completed' ? job.assetId : null,
    openExactLocal,
  );
  const performExport = useCallback(async () => {
    if (!job || job.state !== 'completed') return;
    try {
      const result = await sharePrivatePhoto(async () => {
        const lease = await openLocal(job.assetId, job.quality);
        if (!lease) throw new Error('The private photo copy is unavailable.');
        return lease;
      }, messages.myPhotosExport());
      if (result === 'unavailable') Alert.alert(messages.myPhotosExportUnavailable());
    } catch {
      Alert.alert(messages.myPhotosExportFailed());
    }
  }, [job, messages, openLocal]);
  const exportPhoto = useCallback(() => {
    Alert.alert(messages.myPhotosExportWarningTitle(), messages.myPhotosExportWarning(), [
      { text: messages.myPhotosCancel(), style: 'cancel' },
      { text: messages.myPhotosContinue(), onPress: () => void performExport() },
    ]);
  }, [messages, performExport]);
  const removePhoto = useCallback(() => {
    if (!job) return;
    Alert.alert(
      messages.myPhotosRemoveDownloadedPhoto(),
      messages.myPhotosRemoveDownloadedPhotoWarning(),
      [
        { text: messages.myPhotosCancel(), style: 'cancel' },
        {
          text: messages.myPhotosConfirmRemove(),
          style: 'destructive',
          onPress: () => {
            void remove(job.id)
              .then(() => router.back())
              .catch(() => Alert.alert(messages.myPhotosDownloadFailed()));
          },
        },
      ],
    );
  }, [job, messages, remove]);
  const retryDownload = useCallback(() => {
    if (!job || !['corrupt', 'failed', 'cancelled', 'paused'].includes(job.state)) return;
    void resume(job.id).catch(() => Alert.alert(messages.myPhotosDownloadFailed()));
  }, [job, messages, resume]);

  if (!tripId || !jobId || jobQuery.isPending) {
    return <ContentLoading label={messages.myPhotosPrivatePhotoLoading()} />;
  }
  if (jobQuery.isError || !job || job.state === 'removed') {
    return <ContentError message={messages.myPhotosPreviewUnavailable()} onRetry={() => void jobQuery.refetch()} />;
  }
  if (job.state !== 'completed') {
    return (
      <ContentError
        message={photoDownloadStatusCopy(job.state, messages)}
        {...(['corrupt', 'failed', 'cancelled', 'paused'].includes(job.state)
          ? { onRetry: retryDownload }
          : {})}
      />
    );
  }
  if (!localView) {
    return (
      <View style={styles.root}>
        <ContentLoading label={messages.myPhotosPrivatePhotoLoading()} />
        <SensitiveScreenProtection protectionKey="my-photos-downloaded-viewer" />
      </View>
    );
  }
  const quality = localView.quality === 'original'
    ? messages.myPhotosOriginalQuality()
    : messages.myPhotosOptimizedQuality();
  return (
    <View style={styles.root}>
      <ZoomablePhoto
        accessibilityLabel={messages.myPhotosDownloadedPhotoTitle()}
        privateLocal
        recyclingKey={`${job.id}:local:${localView.quality}`}
        source={{ uri: localView.uri }}
      />
      <View style={styles.topBar}>
        <Pressable accessibilityLabel={messages.myPhotosClose()} accessibilityRole="button" onPress={() => router.back()} style={styles.iconButton}>
          <ChevronLeft color={colors.white} size={29} />
        </Pressable>
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosDownloadedPhotoTitle()}</Text>
      </View>
      <View style={styles.details}>
        <Text style={styles.meta}>{quality}</Text>
        {job.encryptedSizeBytes !== null ? (
          <Text style={styles.meta}>{messages.myPhotosStorageUsed(formatPrivatePhotoBytes(job.encryptedSizeBytes))}</Text>
        ) : null}
        <View style={styles.actions}>
          <Pressable accessibilityLabel={messages.myPhotosExport()} accessibilityRole="button" onPress={exportPhoto} style={styles.action}>
            <Share2 color={colors.white} size={21} />
            <Text style={styles.actionText}>{messages.myPhotosExport()}</Text>
          </Pressable>
          <Pressable accessibilityLabel={messages.myPhotosRemoveDownloadedPhoto()} accessibilityRole="button" onPress={removePhoto} style={styles.action}>
            <Trash2 color={colors.coral} size={21} />
            <Text style={styles.removeText}>{messages.myPhotosRemoveDownloadedPhoto()}</Text>
          </Pressable>
        </View>
      </View>
      <SensitiveScreenProtection protectionKey="my-photos-downloaded-viewer" />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.navy },
  topBar: { position: 'absolute', left: spacing.md, right: spacing.md, top: spacing.xxl, minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  iconButton: { width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(8,41,54,0.8)', alignItems: 'center', justifyContent: 'center' },
  title: { flex: 1, color: colors.white, fontSize: 16, fontWeight: '900', textShadowColor: colors.navy, textShadowRadius: 4 },
  details: { position: 'absolute', left: spacing.md, right: spacing.md, bottom: spacing.xl, gap: spacing.sm, borderRadius: radii.lg, backgroundColor: 'rgba(8,41,54,0.9)', padding: spacing.md },
  meta: { color: colors.white, fontSize: 12, fontWeight: '800' },
  actions: { flexDirection: 'row', gap: spacing.sm },
  action: { minHeight: 48, flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs, borderRadius: radii.pill, borderWidth: 1, borderColor: 'rgba(255,255,255,0.42)', paddingHorizontal: spacing.sm },
  actionText: { flexShrink: 1, color: colors.white, fontSize: 11, fontWeight: '900', textAlign: 'center' },
  removeText: { flexShrink: 1, color: colors.coral, fontSize: 11, fontWeight: '900', textAlign: 'center' },
});
