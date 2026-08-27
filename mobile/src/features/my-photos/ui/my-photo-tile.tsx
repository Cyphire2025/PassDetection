import { Image } from 'expo-image';
import Check from 'lucide-react-native/icons/check';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import Clock3 from 'lucide-react-native/icons/clock-3';
import RotateCcw from 'lucide-react-native/icons/rotate-ccw';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { colors, radii, spacing } from '@/design/theme';

import type { MyPhotosAsset } from '../api/contracts';
import type { MyPhotosImageSourceResolver } from '../media/photo-image-source';
import { useResolvedPhotoImage } from '../media/use-resolved-photo-image';
import { myPhotoTileDescription } from './my-photo-tile-copy';
import type { PhotoTileDownloadState } from './photo-tile-download-state';

type Props = Readonly<{
  asset: MyPhotosAsset;
  resolveSource: MyPhotosImageSourceResolver;
  selected: boolean;
  selectionActive: boolean;
  onOpen: (asset: MyPhotosAsset) => void;
  onToggleSelection: (asset: MyPhotosAsset) => void;
  downloadState: PhotoTileDownloadState | null;
}>;

function MyPhotoTileComponent({
  asset,
  resolveSource,
  selected,
  selectionActive,
  onOpen,
  onToggleSelection,
  downloadState,
}: Props) {
  const messages = useMessages();
  const reduceMotion = useReducedMotion();
  const imageKey = `${asset.asset_id}:${asset.thumbnail.cache_key}`;
  const [failedImageKey, setFailedImageKey] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const recordedResolutionFailure = useRef<string | null>(null);
  const resolved = useResolvedPhotoImage(asset, 'thumbnail', resolveSource, retryNonce);
  const failed = failedImageKey === imageKey || resolved.failed;
  useEffect(() => {
    const attemptKey = `${imageKey}:${retryNonce}`;
    if (!resolved.failed || recordedResolutionFailure.current === attemptKey) return;
    recordedResolutionFailure.current = attemptKey;
    recordMobileMetric('my_photos_thumbnail_failure', 1, { outcome: 'failure' });
  }, [imageKey, resolved.failed, retryNonce]);
  const open = useCallback(() => {
    if (selectionActive) onToggleSelection(asset);
    else onOpen(asset);
  }, [asset, onOpen, onToggleSelection, selectionActive]);
  const longPress = useCallback(() => onToggleSelection(asset), [asset, onToggleSelection]);
  const description = `${myPhotoTileDescription(asset, messages)}${downloadState ? `. ${downloadState.label}` : ''}`;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${description}. ${selected ? messages.myPhotosSelectionCount(1) : ''}`.trim()}
      accessibilityState={{ selected }}
      delayLongPress={300}
      onLongPress={longPress}
      onPress={open}
      style={({ pressed }) => [styles.pressable, pressed && styles.pressed]}>
      <View style={[styles.media, { aspectRatio: Math.min(1.6, Math.max(0.68, asset.aspect_ratio)) }]}>
        <View style={styles.synthetic}>
          <Text style={styles.syntheticMark} accessibilityElementsHidden>GC</Text>
        </View>
        {resolved.source && !failed ? (
          <Image
            accessibilityIgnoresInvertColors
            cachePolicy="memory"
            contentFit="cover"
            key={`${imageKey}:${retryNonce}`}
            onError={() => {
              setFailedImageKey(imageKey);
              recordMobileMetric('my_photos_thumbnail_failure', 1, { outcome: 'failure' });
            }}
            recyclingKey={`${imageKey}:${retryNonce}`}
            source={resolved.source}
            style={StyleSheet.absoluteFill}
            transition={reduceMotion ? 0 : 100}
          />
        ) : null}
        {failed ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={messages.myPhotosRetryThumbnail()}
            onPress={(event) => {
              event.stopPropagation();
              setFailedImageKey(null);
              setRetryNonce((value) => value + 1);
            }}
            style={styles.retry}>
            <RotateCcw color={colors.white} size={17} />
          </Pressable>
        ) : null}
        {asset.preparing ? (
          <View style={styles.status}>
            <Clock3 color={colors.white} size={13} />
            <Text style={styles.statusText}>{messages.myPhotosPreparingPhoto()}</Text>
          </View>
        ) : downloadState ? (
          <View style={styles.status}>
            {downloadState.downloaded ? <Check color={colors.white} size={13} /> : <CloudDownload color={colors.white} size={13} />}
            <Text numberOfLines={1} style={styles.statusText}>{downloadState.label}</Text>
          </View>
        ) : asset.download_qualities.length > 0 ? (
          <View accessibilityLabel={messages.myPhotosDownload()} style={styles.downloadIcon}>
            <CloudDownload color={colors.white} size={15} />
          </View>
        ) : null}
        {selected ? (
          <View style={styles.selection}>
            <Check color={colors.white} size={18} strokeWidth={3} />
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

export const MyPhotoTile = memo(MyPhotoTileComponent, (previous, next) => (
  previous.asset === next.asset
  && previous.resolveSource === next.resolveSource
  && previous.selected === next.selected
  && previous.selectionActive === next.selectionActive
  && previous.downloadState === next.downloadState
  && previous.onOpen === next.onOpen
  && previous.onToggleSelection === next.onToggleSelection
));

const styles = StyleSheet.create({
  pressable: { flex: 1, padding: 2 },
  pressed: { opacity: 0.72 },
  media: { minHeight: 104, overflow: 'hidden', borderRadius: radii.sm, backgroundColor: colors.blueSoft },
  synthetic: { position: 'absolute', inset: 0, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.aquaSoft },
  syntheticMark: { color: colors.blueDeep, fontSize: 18, fontWeight: '900', opacity: 0.45 },
  status: { position: 'absolute', left: spacing.xs, right: spacing.xs, bottom: spacing.xs, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 3, borderRadius: radii.pill, backgroundColor: 'rgba(8,41,54,0.82)', paddingHorizontal: 6, paddingVertical: 4 },
  statusText: { flexShrink: 1, color: colors.white, fontSize: 9, fontWeight: '800' },
  downloadIcon: { position: 'absolute', right: spacing.xs, bottom: spacing.xs, width: 26, height: 26, borderRadius: 13, backgroundColor: 'rgba(8,41,54,0.78)', alignItems: 'center', justifyContent: 'center' },
  selection: { position: 'absolute', right: spacing.xs, top: spacing.xs, width: 29, height: 29, borderRadius: 15, backgroundColor: colors.greenDeep, borderWidth: 2, borderColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  retry: { position: 'absolute', alignSelf: 'center', top: '40%', width: 38, height: 38, borderRadius: 19, backgroundColor: 'rgba(8,41,54,0.88)', alignItems: 'center', justifyContent: 'center' },
});
