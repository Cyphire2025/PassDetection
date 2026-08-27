import type { ImageSource } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import Share2 from 'lucide-react-native/icons/share-2';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, FlatList, Pressable, StyleSheet, Text, View, useWindowDimensions, type ListRenderItem, type ViewToken } from 'react-native';

import { formatInstantDateTime } from '@/core/localization/date-time';
import { useMessages } from '@/core/localization/localization-provider';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import { ContentError, ContentLoading } from '@/design/components/content-state';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

import { MatchFilterSchema, type MatchFilter, type MyPhotosAsset } from '../api/contracts';
import type { PhotoDownloadPlan } from '../downloads/download-manager';
import { myPhotosSnapshotRevisionForFilter } from '../data/gallery-window';
import { photoDownloadPlanView, usePhotoDownloads } from '../hooks/use-photo-downloads';
import { useMyPhotosGallery, useMyPhotosMutations, useMyPhotosSummary } from '../hooks/use-my-photos';
import {
  createMyPhotosImageCacheScope,
  createMyPhotosRemoteImageResolver,
  type MyPhotosImageSourceResolver,
} from '../media/photo-image-source';
import { useResolvedPhotoImage } from '../media/use-resolved-photo-image';
import { ZoomablePhoto } from './zoomable-photo';
import { isMyPhotosAccessRevokedError } from './my-photos-access-error';
import { canSubmitMyPhotoFeedback } from './my-photo-feedback-policy';
import { PhotoDownloadPlanModal } from './photo-download-plan-modal';
import { photoDownloadStatusCopy } from './photo-download-status-copy';
import { sharePrivatePhoto } from './share-private-photo';
import { usePrivatePhotoView } from './use-private-photo-view';

const EMPTY_ASSETS: readonly MyPhotosAsset[] = Object.freeze([]);
const PHOTO_VIEWABILITY_CONFIG = Object.freeze({ itemVisiblePercentThreshold: 70 });
const PHOTO_VISIBLE_POSITION = Object.freeze({ minIndexForVisible: 0 });

type ResolvedViewerPhotoProps = Readonly<{
  accessibilityLabel: string;
  asset: MyPhotosAsset;
  localSource: ImageSource | null;
  recyclingKey: string;
  resolvePreview: MyPhotosImageSourceResolver;
}>;

function ResolvedViewerPhoto({
  accessibilityLabel,
  asset,
  localSource,
  recyclingKey,
  resolvePreview,
}: ResolvedViewerPhotoProps) {
  const resolved = useResolvedPhotoImage(
    asset,
    'preview',
    resolvePreview,
    0,
    localSource === null,
  );
  return (
    <ZoomablePhoto
      accessibilityLabel={accessibilityLabel}
      privateLocal={localSource !== null}
      recyclingKey={recyclingKey}
      source={localSource ?? resolved.source}
    />
  );
}

export function MyPhotoViewerScreen() {
  const messages = useMessages();
  const params = useLocalSearchParams<{ assetId?: string | string[]; filter?: string | string[] }>();
  const requestedAssetId = typeof params.assetId === 'string' ? params.assetId : params.assetId?.[0] ?? '';
  const rawFilter = typeof params.filter === 'string' ? params.filter : params.filter?.[0];
  const parsedFilter = MatchFilterSchema.safeParse(rawFilter);
  const filter: MatchFilter = parsedFilter.success ? parsedFilter.data : 'best';
  const trips = useTrips();
  const session = useSessionStore((state) => state.session);
  const tripId = trips.selectedTripId;
  const summary = useMyPhotosSummary(tripId);
  const summaryValue = summary.data?.value;
  const gallery = useMyPhotosGallery(tripId, filter, summary.data, 'viewer');
  const mutations = useMyPhotosMutations(tripId);
  const downloads = usePhotoDownloads(tripId);
  const { activatePlan, openLocal, planSelected } = downloads;
  const [downloadPlan, setDownloadPlan] = useState<PhotoDownloadPlan | null>(null);
  const { width } = useWindowDimensions();
  const [viewPosition, setViewPosition] = useState<Readonly<{
    requestedAssetId: string;
    visibleAssetId: string;
  }> | null>(null);
  const pages = gallery.data?.pages;
  const assets = useMemo(() => {
    if (!pages) return EMPTY_ASSETS;
    const result: MyPhotosAsset[] = [];
    const seen = new Set<string>();
    for (const page of pages) {
      for (const asset of page.value.items) {
        if (!seen.has(asset.asset_id)) {
          seen.add(asset.asset_id);
          result.push(asset);
        }
      }
    }
    return result;
  }, [pages]);
  const requestedIndex = useMemo(
    () => assets.findIndex((asset) => asset.asset_id === requestedAssetId),
    [assets, requestedAssetId],
  );
  const visibleIndex = viewPosition?.requestedAssetId === requestedAssetId
    ? assets.findIndex((asset) => asset.asset_id === viewPosition.visibleAssetId)
    : -1;
  const currentIndex = visibleIndex >= 0 ? visibleIndex : Math.max(0, requestedIndex);
  const positionState: 'pending' | 'ready' | 'missing' = requestedIndex >= 0
    ? 'ready'
    : gallery.isFetching
      ? 'pending'
      : 'missing';
  const onViewableItemsChanged = useCallback((event: Readonly<{ viewableItems: ViewToken<MyPhotosAsset>[] }>) => {
    const next = event.viewableItems[0]?.item;
    if (next) setViewPosition({ requestedAssetId, visibleAssetId: next.asset_id });
  }, [requestedAssetId]);
  const fetchNextPage = gallery.fetchNextPage;
  const hasNextPage = gallery.hasNextPage;
  const isFetchingNextPage = gallery.isFetchingNextPage;
  const loadNext = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);
  const fetchPreviousPage = gallery.fetchPreviousPage;
  const hasPreviousPage = gallery.hasPreviousPage;
  const isFetchingPreviousPage = gallery.isFetchingPreviousPage;
  const loadPrevious = useCallback(() => {
    if (hasPreviousPage && !isFetchingPreviousPage) void fetchPreviousPage();
  }, [fetchPreviousPage, hasPreviousPage, isFetchingPreviousPage]);
  const current = positionState === 'ready' ? assets[currentIndex] ?? null : null;
  const localView = usePrivatePhotoView(current?.asset_id ?? null, openLocal);
  const imageNamespace = session?.principal.principalType === 'passenger'
    ? principalAccountNamespace(session.principal)
    : null;
  const imagePassengerId = session?.principal.principalType === 'passenger'
    ? session.principal.passengerId
    : null;
  const imageAccessToken = session?.accessToken ?? null;
  const imageCacheScope = useMemo(
    () => imageNamespace && imagePassengerId
      ? createMyPhotosImageCacheScope(imageNamespace, imagePassengerId)
      : null,
    [imageNamespace, imagePassengerId],
  );
  const imageResolver = useMemo(
    () => tripId && imageAccessToken && imageCacheScope
      ? createMyPhotosRemoteImageResolver(tripId, imageCacheScope)
      : null,
    [imageAccessToken, imageCacheScope, tripId],
  );
  useEffect(() => () => {
    void imageResolver?.clear();
  }, [imageResolver]);
  const resolvePreview = useCallback((asset: MyPhotosAsset, signal?: AbortSignal) => (
    imageResolver?.resolve(asset, 'preview', signal) ?? Promise.resolve(null)
  ), [imageResolver]);
  const viewerTotalCount = gallery.data?.pages[0]?.value.total_count ?? assets.length;
  const renderPhoto = useCallback<ListRenderItem<MyPhotosAsset>>(({ item, index }) => (
    <View style={[styles.photoPage, { width }]}>
      <ResolvedViewerPhoto
        accessibilityLabel={messages.myPhotosPhotoPosition(
          gallery.residentStartIndex + index + 1,
          viewerTotalCount,
        )}
        asset={item}
        localSource={localView?.assetId === item.asset_id ? { uri: localView.uri } : null}
        recyclingKey={localView?.assetId === item.asset_id
          ? `${item.asset_id}:local:${localView.quality}`
          : `${item.asset_id}:${item.preview.cache_key}`}
        resolvePreview={resolvePreview}
      />
    </View>
  ), [gallery.residentStartIndex, localView, messages, resolvePreview, viewerTotalCount, width]);
  const currentJob = useMemo(() => {
    if (!current) return null;
    const matching = (downloads.jobs.data ?? []).filter((job) => job.assetId === current.asset_id);
    return matching.find((job) => job.state === 'completed' && job.quality === 'original')
      ?? matching.find((job) => job.state === 'completed')
      ?? matching.find((job) => job.state !== 'removed')
      ?? null;
  }, [current, downloads.jobs.data]);
  const feedback = useCallback((value: 'this_is_me' | 'not_me') => {
    if (!current) return;
    mutations.feedback.mutate({ assetId: current.asset_id, feedback: value });
  }, [current, mutations.feedback]);
  const download = useCallback(async () => {
    if (!current || !summaryValue || downloads.plan.isPending) return;
    try {
      setDownloadPlan(await planSelected(
        [current],
        myPhotosSnapshotRevisionForFilter(summaryValue, filter),
      ));
    } catch {
      Alert.alert(messages.myPhotosDownloadFailed(), messages.myPhotosRecoverableError());
    }
  }, [current, downloads.plan.isPending, filter, messages, planSelected, summaryValue]);
  const activateDownloadPlan = useCallback(async (
    quality: 'original' | 'optimized',
    wifiOnly: boolean,
  ) => {
    if (!downloadPlan) return;
    try {
      await activatePlan(downloadPlan, quality, wifiOnly);
      setDownloadPlan(null);
    } catch {
      Alert.alert(messages.myPhotosDownloadFailed(), messages.myPhotosRecoverableError());
    }
  }, [activatePlan, downloadPlan, messages]);
  const performExport = useCallback(async () => {
    if (!current || !currentJob || currentJob.state !== 'completed') {
      Alert.alert(messages.myPhotosExportRequiresDownload());
      return;
    }
    try {
      const result = await sharePrivatePhoto(async () => {
        const lease = await openLocal(current.asset_id, currentJob.quality);
        if (!lease) throw new Error('The private photo copy is unavailable.');
        return lease;
      }, messages.myPhotosExport());
      if (result === 'unavailable') Alert.alert(messages.myPhotosExportUnavailable());
    } catch {
      Alert.alert(messages.myPhotosExportFailed());
    }
  }, [current, currentJob, messages, openLocal]);
  const exportPhoto = useCallback(() => {
    Alert.alert(messages.myPhotosExportWarningTitle(), messages.myPhotosExportWarning(), [
      { text: messages.myPhotosCancel(), style: 'cancel' },
      {
        text: messages.myPhotosContinue(),
        onPress: () => void performExport(),
      },
    ]);
  }, [messages, performExport]);

  if (!tripId || summary.isPending || gallery.isPending) return <ContentLoading label={messages.loading()} />;
  if (isMyPhotosAccessRevokedError(summary.error) || isMyPhotosAccessRevokedError(gallery.error)) {
    return <ContentError message={messages.myPhotosAccessRevoked()} />;
  }
  if (summary.isError || gallery.isError || !summary.data) {
    return <ContentError message={messages.myPhotosRecoverableError()} onRetry={() => void gallery.refetch()} />;
  }
  if (positionState === 'missing') {
    return (
      <ContentError
        message={messages.myPhotosPreviewUnavailable()}
        onRetry={() => void gallery.refetch()}
      />
    );
  }
  if (positionState === 'pending') return <ContentLoading label={messages.loading()} />;
  if (!current) return <ContentError message={messages.myPhotosPreviewUnavailable()} onRetry={() => void gallery.refetch()} />;
  return (
    <View style={styles.root}>
      <FlatList
        data={assets}
        decelerationRate="fast"
        getItemLayout={(_data, index) => ({ length: width, offset: width * index, index })}
        horizontal
        initialScrollIndex={requestedIndex}
        keyExtractor={(asset) => asset.asset_id}
        maintainVisibleContentPosition={PHOTO_VISIBLE_POSITION}
        onEndReached={loadNext}
        onEndReachedThreshold={0.6}
        onStartReached={loadPrevious}
        onStartReachedThreshold={0.6}
        onViewableItemsChanged={onViewableItemsChanged}
        pagingEnabled
        renderItem={renderPhoto}
        showsHorizontalScrollIndicator={false}
        viewabilityConfig={PHOTO_VIEWABILITY_CONFIG}
        {...MOBILE_LIST_WINDOWING.compactInteractive}
      />
      <View style={styles.topBar}>
        <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosClose()} onPress={() => router.back()} style={styles.iconButton}>
          <ChevronLeft color={colors.white} size={29} />
        </Pressable>
        <Text accessibilityLiveRegion="polite" style={styles.position}>{messages.myPhotosPhotoPosition(
          gallery.residentStartIndex + currentIndex + 1,
          viewerTotalCount,
        )}</Text>
      </View>
      <View style={styles.details}>
        {current.captured_at ? (
          <Text style={styles.captured}>{messages.myPhotosCaptured(formatInstantDateTime(
            current.captured_at,
            { timeZone: trips.selectedTrip?.timeZone },
          ))}</Text>
        ) : null}
        {canSubmitMyPhotoFeedback(current) ? (
          <View style={styles.feedbackRow}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{
                disabled: mutations.feedback.isPending,
                selected: current.feedback === 'this_is_me',
              }}
              disabled={mutations.feedback.isPending}
              onPress={() => feedback('this_is_me')}
              style={[styles.feedback, current.feedback === 'this_is_me' && styles.feedbackSelected]}>
              <Text style={styles.feedbackText}>{messages.myPhotosThisIsMe()}</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{
                disabled: mutations.feedback.isPending,
                selected: current.feedback === 'not_me',
              }}
              disabled={mutations.feedback.isPending}
              onPress={() => feedback('not_me')}
              style={[styles.feedback, current.feedback === 'not_me' && styles.feedbackRejected]}>
              <Text style={styles.feedbackText}>{messages.myPhotosNotMe()}</Text>
            </Pressable>
          </View>
        ) : null}
        <View style={styles.actionRow}>
          <View style={styles.action}>
            <PrimaryButton accessibilityLabel={messages.myPhotosDownload()} label={messages.myPhotosDownload()} onPress={download} />
          </View>
          <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosExport()} onPress={exportPhoto} style={styles.share}>
            <Share2 color={colors.white} size={22} />
          </Pressable>
        </View>
        {current.preparing || (currentJob && currentJob.state !== 'completed') ? (
          <View style={styles.preparing}>
            <CloudDownload color={colors.green} size={17} />
            <Text accessibilityLiveRegion="polite" style={styles.preparingText}>
              {currentJob
                ? photoDownloadStatusCopy(currentJob.state, messages)
                : messages.myPhotosPreparingPhoto()}
            </Text>
          </View>
        ) : null}
      </View>
      <SensitiveScreenProtection protectionKey="my-photos-viewer" />
      <PhotoDownloadPlanModal
        busy={downloads.activate.isPending}
        onCancel={() => setDownloadPlan(null)}
        onConfirm={(quality, wifiOnly) => void activateDownloadPlan(quality, wifiOnly)}
        plan={downloadPlan ? photoDownloadPlanView(downloadPlan) : null}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.navy },
  photoPage: { flex: 1 },
  topBar: { position: 'absolute', left: spacing.md, right: spacing.md, top: spacing.xxl, minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  iconButton: { width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(8,41,54,0.8)', alignItems: 'center', justifyContent: 'center' },
  position: { flex: 1, color: colors.white, fontSize: 14, fontWeight: '900', textAlign: 'center', textShadowColor: colors.navy, textShadowRadius: 4 },
  details: { position: 'absolute', left: spacing.md, right: spacing.md, bottom: spacing.xl, gap: spacing.sm, borderRadius: radii.lg, backgroundColor: 'rgba(8,41,54,0.9)', padding: spacing.md },
  captured: { color: colors.white, fontSize: 12, fontWeight: '700' },
  feedbackRow: { flexDirection: 'row', gap: spacing.sm },
  feedback: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radii.pill, borderWidth: 1, borderColor: 'rgba(255,255,255,0.42)' },
  feedbackSelected: { borderColor: colors.green, backgroundColor: 'rgba(202,207,66,0.22)' },
  feedbackRejected: { borderColor: colors.coral, backgroundColor: 'rgba(242,122,103,0.22)' },
  feedbackText: { color: colors.white, fontSize: 13, fontWeight: '900' },
  actionRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  action: { flex: 1 },
  share: { width: 54, height: 54, borderRadius: 27, borderWidth: 1, borderColor: 'rgba(255,255,255,0.4)', alignItems: 'center', justifyContent: 'center' },
  preparing: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  preparingText: { color: colors.white, fontSize: 12, fontWeight: '800' },
});
