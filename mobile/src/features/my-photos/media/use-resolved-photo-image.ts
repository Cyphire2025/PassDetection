import { useEffect, useMemo, useState } from 'react';

import type { MyPhotosAsset } from '../api/contracts';
import type { MyPhotosImageSourceResolver, ResolvedMyPhotosImage } from './photo-image-source';

type ResolvedState = Readonly<{
  failed: boolean;
  key: string;
  value: ResolvedMyPhotosImage | null;
}>;

export function useResolvedPhotoImage(
  asset: MyPhotosAsset,
  variant: 'thumbnail' | 'preview',
  resolveSource: MyPhotosImageSourceResolver,
  refreshKey = 0,
  enabled = true,
): Readonly<{
  failed: boolean;
  source: ResolvedMyPhotosImage['source'] | null;
}> {
  const key = `${asset.asset_id}:${asset[variant].cache_key}:${variant}:${refreshKey}`;
  const [state, setState] = useState<ResolvedState>(() => ({ failed: false, key, value: null }));

  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;
    let expiryTimer: ReturnType<typeof setTimeout> | null = null;

    const load = async (): Promise<void> => {
      controller?.abort(new Error('The previous photo preview request was replaced.'));
      const requestController = new AbortController();
      controller = requestController;
      try {
        const value = await resolveSource(asset, requestController.signal);
        if (!active || requestController.signal.aborted) return;
        setState({ failed: false, key, value });
        if (value) {
          const remaining = Math.max(1, value.expiresAtMs - Date.now());
          expiryTimer = setTimeout(() => {
            if (!active) return;
            // Drop the signed URL before obtaining its replacement so it is
            // never retained beyond the provider authorization lifetime.
            setState({ failed: false, key, value: null });
            void load();
          }, remaining);
        }
      } catch {
        if (!active || requestController.signal.aborted) return;
        setState({ failed: true, key, value: null });
      }
    };

    if (enabled) void load();
    return () => {
      active = false;
      controller?.abort(new Error('The photo preview left the visible window.'));
      if (expiryTimer) clearTimeout(expiryTimer);
    };
  }, [asset, enabled, key, resolveSource]);

  return useMemo(() => enabled && state.key === key
    ? { failed: state.failed, source: state.value?.source ?? null }
    : { failed: false, source: null }, [enabled, key, state]);
}
