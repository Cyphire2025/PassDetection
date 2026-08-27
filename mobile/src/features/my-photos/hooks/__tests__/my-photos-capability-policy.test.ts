import type { MyPhotosSummary } from '../../api/contracts';
import type { CachedResult } from '../../data/my-photos-repository';
import {
  myPhotosCapabilityDecision,
  shouldBlockMyPhotosRoute,
} from '../my-photos-capability-policy';

function summary(
  featureEnabled: boolean,
  source: 'network' | 'offline' = 'network',
): CachedResult<MyPhotosSummary> {
  return {
    source,
    cachedAt: source === 'offline' ? '2026-08-28T00:00:00.000Z' : null,
    partial: false,
    value: {
      capability: { feature_enabled: featureEnabled },
      experience_state: featureEnabled ? 'matches_ready' : 'feature_unavailable',
    },
  } as CachedResult<MyPhotosSummary>;
}

test('only a fresh server-enabled summary reveals My Photos', () => {
  expect(myPhotosCapabilityDecision(summary(true))).toEqual({
    visible: true,
    confirmedNetworkDisabled: false,
  });
  expect(myPhotosCapabilityDecision(undefined)).toEqual({
    visible: false,
    confirmedNetworkDisabled: false,
  });
  expect(myPhotosCapabilityDecision(summary(true, 'offline'))).toEqual({
    visible: false,
    confirmedNetworkDisabled: false,
  });
  expect(myPhotosCapabilityDecision(summary(true), new Error('offline'))).toEqual({
    visible: false,
    confirmedNetworkDisabled: false,
  });
  expect(myPhotosCapabilityDecision(summary(true), null, false)).toEqual({
    visible: false,
    confirmedNetworkDisabled: false,
  });
});

test('only a fresh server-disabled summary authorizes destructive cleanup', () => {
  expect(myPhotosCapabilityDecision(summary(false))).toEqual({
    visible: false,
    confirmedNetworkDisabled: true,
  });
  expect(myPhotosCapabilityDecision(summary(false, 'offline')).confirmedNetworkDisabled).toBe(false);
  expect(
    myPhotosCapabilityDecision(summary(false), new Error('refetch failed')).confirmedNetworkDisabled,
  ).toBe(false);
  expect(myPhotosCapabilityDecision(summary(false), null, false).confirmedNetworkDisabled).toBe(false);
});

test.each([
  '/my-photos',
  '/my-photos/face-scan',
  '/my-photos/photo/asset-a',
  '/my-photos/downloaded/job-a',
  '/my-photos/storage',
])('blocks direct My Photos route %s unless the capability is visible', (pathname) => {
  expect(shouldBlockMyPhotosRoute(pathname, myPhotosCapabilityDecision(undefined))).toBe(true);
  expect(shouldBlockMyPhotosRoute(pathname, myPhotosCapabilityDecision(summary(true)))).toBe(false);
});

test('does not affect unrelated passenger routes', () => {
  expect(shouldBlockMyPhotosRoute('/trip', myPhotosCapabilityDecision(undefined))).toBe(false);
});
