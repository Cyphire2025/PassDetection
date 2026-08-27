import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View, type ListRenderItem, type ViewToken } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { MOBILE_LIST_WINDOWING, MY_PHOTOS_CLIENT_BUDGET } from '@/core/performance/mobile-performance-budgets';
import { ContentEmpty, ContentError } from '@/design/components/content-state';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';

import type { MatchFilter, MyPhotosAsset, MyPhotosSummary } from '../api/contracts';
import type { MyPhotosImageSourceResolver } from '../media/photo-image-source';
import type { CachedResult } from '../data/my-photos-repository';
import { myPhotosSnapshotRevisionForFilter } from '../data/gallery-window';
import { useMyPhotosGallery } from '../hooks/use-my-photos';
import { myPhotosGalleryEmptyCopy } from './gallery-empty-state';
import {
  emptyGallerySelection,
  canSelectEveryFilterResult,
  galleryAssetSelected,
  gallerySelectionCount,
  selectEveryFilterResult,
  toggleGalleryAsset,
  type GallerySelection,
} from './gallery-selection';
import { readGalleryScrollAnchor, rememberGalleryScrollAnchor } from './gallery-scroll-anchor';
import { initialMyPhotosGalleryFilter } from './gallery-visibility';
import { MyPhotoTile } from './my-photo-tile';
import { MyPhotosGallerySkeleton } from './my-photos-gallery-skeleton';
import { myPhotosRequestErrorPresentation } from './my-photos-request-state';
import type { PhotoTileDownloadState } from './photo-tile-download-state';

type Props = Readonly<{
  tripId: string;
  accountBoundary: string;
  summary: CachedResult<MyPhotosSummary>;
  resolveThumbnail: MyPhotosImageSourceResolver;
  onDownload: (selection: GallerySelection, assets: readonly MyPhotosAsset[], filter: MatchFilter) => void;
  onDownloadAllMatches: () => void;
  downloadStates: ReadonlyMap<string, PhotoTileDownloadState>;
  onCacheStateChange: (state: Readonly<{
    source: 'network' | 'offline';
    partial: boolean;
  }>) => void;
}>;

const EMPTY_ASSETS: readonly MyPhotosAsset[] = Object.freeze([]);
const GRID_VIEWABILITY_CONFIG = Object.freeze({ itemVisiblePercentThreshold: 1 });
const GRID_VISIBLE_POSITION = Object.freeze({ minIndexForVisible: 0 });
type MyPhotosGridList = FlatList<MyPhotosAsset>;

export function MyPhotosGallery({ tripId, accountBoundary, summary, resolveThumbnail, onDownload, onDownloadAllMatches, downloadStates, onCacheStateChange }: Props) {
  const messages = useMessages();
  const filterBoundary = `${tripId}:${summary.value.gallery.published_revision}:${summary.value.results.snapshot_revision}`;
  const recommendedFilter = initialMyPhotosGalleryFilter(summary.value);
  const [filterState, setFilterState] = useState<Readonly<{
    boundary: string;
    filter: MatchFilter;
  }>>(() => ({ boundary: filterBoundary, filter: recommendedFilter }));
  const filter = filterState.boundary === filterBoundary
    ? filterState.filter
    : recommendedFilter;
  const gallery = useMyPhotosGallery(tripId, filter, summary);
  const snapshotRevision = myPhotosSnapshotRevisionForFilter(summary.value, filter);
  const selectionBoundary = `${tripId}:${snapshotRevision}:${filter}`;
  const [selectionState, setSelectionState] = useState<Readonly<{
    boundary: string;
    selection: GallerySelection;
    assets: ReadonlyMap<string, MyPhotosAsset>;
  }>>(() => ({ boundary: selectionBoundary, selection: emptyGallerySelection, assets: new Map() }));
  const selection = selectionState.boundary === selectionBoundary
    ? selectionState.selection
    : emptyGallerySelection;
  const firstContentStartedAt = useRef<number | null>(null);
  const firstContentRecorded = useRef(false);
  const blankAreaRecorded = useRef(false);
  const pages = gallery.data?.pages;
  const cacheState = useMemo(() => ({
    source: summary.source === 'offline' || pages?.some((page) => page.source === 'offline')
      ? 'offline' as const
      : 'network' as const,
    partial: summary.partial || Boolean(pages?.some((page) => page.partial)),
  }), [pages, summary.partial, summary.source]);
  useEffect(() => onCacheStateChange(cacheState), [cacheState, onCacheStateChange]);
  const listRef = useRef<MyPhotosGridList>(null);
  const assets = useMemo(() => {
    if (!pages) return EMPTY_ASSETS;
    const values: MyPhotosAsset[] = [];
    const seen = new Set<string>();
    for (const page of pages) {
      for (const asset of page.value.items) {
        if (!seen.has(asset.asset_id)) {
          seen.add(asset.asset_id);
          values.push(asset);
        }
      }
    }
    return values;
  }, [pages]);
  const totalCount = filter === 'best'
    ? summary.value.search?.best_match_count ?? 0
    : filter === 'possible'
      ? summary.value.search?.possible_match_count ?? 0
      : summary.value.gallery.total_asset_count;
  const scrollBoundary = `${accountBoundary}:${tripId}:${snapshotRevision}:${filter}`;
  const assetsRef = useRef(assets);
  useEffect(() => {
    assetsRef.current = assets;
  }, [assets]);
  useFocusEffect(useCallback(() => {
    const anchor = readGalleryScrollAnchor(scrollBoundary);
    if (!anchor) return;
    const index = assetsRef.current.findIndex((asset) => asset.asset_id === anchor.assetId);
    if (index < 0) return;
    requestAnimationFrame(() => listRef.current?.scrollToIndex({
      index,
      animated: false,
      viewPosition: 0,
    }));
  }, [scrollBoundary]));
  const selectedCount = gallerySelectionCount(selection);
  const selectionActive = selectedCount > 0;
  const galleryErrorPresentation = useMemo(
    () => myPhotosRequestErrorPresentation(gallery.error, messages),
    [gallery.error, messages],
  );
  const galleryErrorMessage = `${galleryErrorPresentation.title} ${galleryErrorPresentation.message}`;
  const emptyCopy = myPhotosGalleryEmptyCopy(filter, messages);

  useEffect(() => {
    firstContentStartedAt.current = performance.now();
    firstContentRecorded.current = false;
    blankAreaRecorded.current = false;
  }, [selectionBoundary]);
  useEffect(() => {
    if (assets.length === 0 || firstContentRecorded.current) return;
    firstContentRecorded.current = true;
    recordMobileMetric(
      'my_photos_gallery_first_content',
      Math.max(0, performance.now() - (firstContentStartedAt.current ?? performance.now())),
      { outcome: summary.source === 'offline' ? 'offline' : 'success' },
    );
  }, [assets.length, summary.source]);
  useEffect(() => {
    if (gallery.isError) recordMobileMetric('my_photos_page_failure', 1, { outcome: 'failure' });
  }, [gallery.isError]);

  const changeFilter = useCallback((next: MatchFilter) => {
    setFilterState({ boundary: filterBoundary, filter: next });
  }, [filterBoundary]);
  const toggleSelection = useCallback((asset: MyPhotosAsset) => {
    setSelectionState((current) => {
      const currentSelection = current.boundary === selectionBoundary
        ? current.selection
        : emptyGallerySelection;
      const next = toggleGalleryAsset(
        currentSelection,
        asset.asset_id,
      );
      const values = new Map(current.boundary === selectionBoundary ? current.assets : []);
      if (galleryAssetSelected(next, asset.asset_id)) {
        values.set(asset.asset_id, asset);
      } else {
        values.delete(asset.asset_id);
      }
      return { boundary: selectionBoundary, selection: next, assets: values };
    });
  }, [selectionBoundary]);
  const openAsset = useCallback((asset: MyPhotosAsset) => {
    router.push({
      pathname: '/(passenger)/my-photos/photo/[assetId]',
      params: { assetId: asset.asset_id, filter },
    });
  }, [filter]);
  const renderItem = useCallback<ListRenderItem<MyPhotosAsset>>(({ item }) => (
    <MyPhotoTile
      asset={item}
      downloadState={downloadStates.get(item.asset_id) ?? null}
      onOpen={openAsset}
      onToggleSelection={toggleSelection}
      selected={galleryAssetSelected(selection, item.asset_id)}
      selectionActive={selectionActive}
      resolveSource={resolveThumbnail}
    />
  ), [downloadStates, openAsset, resolveThumbnail, selection, selectionActive, toggleSelection]);
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
  const download = useCallback(() => {
    const values = selectionState.boundary === selectionBoundary
      ? [...selectionState.assets.values()]
      : EMPTY_ASSETS;
    onDownload(selection, values, filter);
  }, [filter, onDownload, selection, selectionBoundary, selectionState]);
  const clearSelection = useCallback(() => {
    setSelectionState({
      boundary: selectionBoundary,
      selection: emptyGallerySelection,
      assets: new Map(),
    });
  }, [selectionBoundary]);
  const selectAllInFilter = useCallback(() => {
    if (!canSelectEveryFilterResult(filter) || totalCount < 1) return;
    setSelectionState({
      boundary: selectionBoundary,
      selection: selectEveryFilterResult(totalCount),
      assets: new Map(),
    });
  }, [filter, selectionBoundary, totalCount]);
  const trackBlankArea = useCallback((event: Readonly<{ viewableItems: ViewToken<MyPhotosAsset>[] }>) => {
    const first = event.viewableItems.find((item) => item.isViewable && item.item);
    if (first?.item && typeof first.index === 'number') {
      rememberGalleryScrollAnchor(scrollBoundary, {
        assetId: first.item.asset_id,
        absoluteIndex: gallery.residentStartIndex + first.index,
      });
    }
    if (assets.length === 0 || event.viewableItems.length > 0 || blankAreaRecorded.current) return;
    blankAreaRecorded.current = true;
    recordMobileMetric('my_photos_grid_blank_incident', 1, { outcome: 'partial' });
  }, [assets.length, gallery.residentStartIndex, scrollBoundary]);
  const handleScrollToIndexFailed = useCallback((info: Readonly<{
    index: number;
    averageItemLength: number;
  }>) => {
    listRef.current?.scrollToOffset({
      animated: false,
      offset: Math.max(0, info.averageItemLength * Math.floor(info.index / MY_PHOTOS_CLIENT_BUDGET.columns)),
    });
  }, []);

  const filters: readonly Readonly<{ value: MatchFilter; label: string; visible: boolean }>[] = [
    { value: 'best', label: messages.myPhotosBest(), visible: true },
    { value: 'possible', label: messages.myPhotosPossible(), visible: true },
    { value: 'all', label: messages.myPhotosAllGroup(), visible: summary.value.gallery.all_group_photos_enabled },
  ];

  return (
    <View style={styles.container}>
      <View accessibilityRole="tablist" style={styles.filters}>
        {filters.map((item) => item.visible ? (
          <Pressable
            accessibilityRole="tab"
            accessibilityState={{ selected: filter === item.value }}
            key={item.value}
            onPress={() => changeFilter(item.value)}
            style={[styles.filter, filter === item.value && styles.filterActive]}>
            <Text style={[styles.filterText, filter === item.value && styles.filterTextActive]}>{item.label}</Text>
          </Pressable>
        ) : null)}
      </View>
      <View style={styles.selectionBar}>
        <Text accessibilityLiveRegion="polite" style={styles.selectionCount}>
          {selectionActive ? messages.myPhotosSelectionCount(selectedCount) : messages.myPhotosPhotosFound(totalCount)}
        </Text>
        {selectionActive ? (
          <Pressable
            accessibilityRole="button"
            onPress={clearSelection}
            style={styles.textButton}>
            <Text style={styles.textButtonLabel}>{messages.myPhotosClearSelection()}</Text>
          </Pressable>
        ) : canSelectEveryFilterResult(filter) && totalCount > 0 ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={messages.myPhotosSelectAllFilter(
              filter === 'best' ? messages.myPhotosBest() : messages.myPhotosPossible(),
            )}
            onPress={selectAllInFilter}
            style={styles.textButton}>
            <Text style={styles.textButtonLabel}>{messages.myPhotosSelectAllFilter(
              filter === 'best' ? messages.myPhotosBest() : messages.myPhotosPossible(),
            )}</Text>
          </Pressable>
        ) : null}
      </View>
      {filter === 'all' ? (
        <Text accessibilityRole="text" style={styles.selectionPolicy}>
          {messages.myPhotosAllGroupSelectionPolicy()}
        </Text>
      ) : null}
      {selectionActive ? (
        <View style={styles.downloadBar}>
          <PrimaryButton
            label={messages.myPhotosDownloadSelected()}
            onPress={download}
          />
        </View>
      ) : summary.value.results.match_count > 0 ? (
        <View style={styles.downloadBar}>
          <PrimaryButton label={messages.myPhotosDownloadAll()} tone="secondary" onPress={onDownloadAllMatches} />
        </View>
      ) : null}
      {gallery.isError && assets.length > 0 ? (
        <View style={styles.inlineError}>
          <ContentError message={galleryErrorMessage} onRetry={() => void gallery.refetch()} />
        </View>
      ) : null}
      <FlatList
        columnWrapperStyle={styles.row}
        contentContainerStyle={styles.grid}
        data={assets}
        extraData={selection}
        key={filter}
        keyExtractor={(asset) => asset.asset_id}
        maintainVisibleContentPosition={GRID_VISIBLE_POSITION}
        numColumns={MY_PHOTOS_CLIENT_BUDGET.columns}
        onEndReached={loadNext}
        onEndReachedThreshold={MY_PHOTOS_CLIENT_BUDGET.nextPagePrefetchThreshold}
        onStartReached={loadPrevious}
        onStartReachedThreshold={MY_PHOTOS_CLIENT_BUDGET.nextPagePrefetchThreshold}
        onScrollToIndexFailed={handleScrollToIndexFailed}
        onViewableItemsChanged={trackBlankArea}
        renderItem={renderItem}
        ref={listRef}
        {...MOBILE_LIST_WINDOWING.photoGrid}
        viewabilityConfig={GRID_VIEWABILITY_CONFIG}
        ListEmptyComponent={gallery.isPending ? (
          <MyPhotosGallerySkeleton />
        ) : gallery.isError ? (
          <ContentError message={galleryErrorMessage} onRetry={() => void gallery.refetch()} />
        ) : (
          <ContentEmpty title={emptyCopy.title} message={emptyCopy.message} />
        )}
        ListHeaderComponent={gallery.isFetchingPreviousPage ? (
          <ActivityIndicator accessibilityLabel={messages.loading()} color={colors.greenDeep} style={styles.loader} />
        ) : gallery.isFetchPreviousPageError ? (
          <ContentError message={galleryErrorMessage} onRetry={loadPrevious} />
        ) : null}
        ListFooterComponent={gallery.isFetchingNextPage ? (
          <ActivityIndicator accessibilityLabel={messages.loading()} color={colors.greenDeep} style={styles.loader} />
        ) : gallery.isFetchNextPageError ? (
          <ContentError message={galleryErrorMessage} onRetry={loadNext} />
        ) : null}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, gap: spacing.sm },
  filters: { flexDirection: 'row', gap: spacing.xs, paddingHorizontal: spacing.lg },
  filter: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radii.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceStrong, paddingHorizontal: spacing.sm },
  filterActive: { borderColor: colors.greenDeep, backgroundColor: colors.greenSoft },
  filterText: { color: colors.inkMuted, fontSize: 12, fontWeight: '800', textAlign: 'center' },
  filterTextActive: { color: colors.greenDeep },
  selectionBar: { minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm, paddingHorizontal: spacing.lg },
  selectionCount: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  textButton: { minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.sm },
  textButtonLabel: { color: colors.greenDeep, fontSize: 12, fontWeight: '900', textAlign: 'right' },
  selectionPolicy: { color: colors.inkMuted, fontSize: 12, lineHeight: 18, paddingHorizontal: spacing.lg },
  downloadBar: { paddingHorizontal: spacing.lg },
  inlineError: { paddingHorizontal: spacing.lg },
  grid: { flexGrow: 1, paddingHorizontal: spacing.md, paddingBottom: spacing.xxl },
  row: { alignItems: 'flex-start' },
  loader: { paddingVertical: spacing.xl },
});
