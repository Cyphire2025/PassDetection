import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { recordMobileMetric } from '@/core/observability/mobile-observability';

import type { DownloadQuality } from '../api/contracts';
import type { LocalPhotoLease } from '../downloads/download-manager';

type OpenLocalPhoto = (
  assetId: string,
  quality: DownloadQuality,
  signal?: AbortSignal,
) => Promise<LocalPhotoLease | null>;

export type PrivatePhotoView = Readonly<{
  assetId: string;
  uri: string;
  mimeType: LocalPhotoLease['mimeType'];
  quality: DownloadQuality;
}>;

export function usePrivatePhotoView(
  assetId: string | null,
  openLocal: OpenLocalPhoto,
): PrivatePhotoView | null {
  const [lifecycle, setLifecycle] = useState(() => ({
    foreground: AppState.currentState === 'active',
    version: 0,
  }));
  const [view, setView] = useState<Readonly<{
    boundary: string;
    value: PrivatePhotoView;
  }> | null>(null);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      setLifecycle((current) => ({
        foreground: state === 'active',
        version: current.version + 1,
      }));
    });
    return () => subscription.remove();
  }, []);

  const boundary = `${lifecycle.version}:${lifecycle.foreground ? 'active' : 'inactive'}:${assetId ?? ''}`;
  useEffect(() => {
    if (!lifecycle.foreground || !assetId) return;
    const controller = new AbortController();
    let mounted = true;
    let lease: LocalPhotoLease | null = null;
    void (async () => {
      try {
        lease = await openLocal(assetId, 'original', controller.signal)
          ?? await openLocal(assetId, 'optimized', controller.signal);
        if (!lease) return;
        if (!mounted || controller.signal.aborted) {
          lease.release();
          lease = null;
          return;
        }
        setView({
          boundary,
          value: {
            assetId,
            uri: lease.uri,
            mimeType: lease.mimeType,
            quality: lease.quality,
          },
        });
      } catch {
        if (!controller.signal.aborted) {
          recordMobileMetric('my_photos_local_view_failure', 1, { outcome: 'failure' });
        }
      }
    })();
    return () => {
      mounted = false;
      controller.abort(new Error('Private photo view changed.'));
      lease?.release();
      lease = null;
    };
  }, [assetId, boundary, lifecycle.foreground, openLocal]);

  return lifecycle.foreground && view?.boundary === boundary ? view.value : null;
}
