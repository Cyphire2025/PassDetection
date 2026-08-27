import { ApiError } from '@/core/api/client';
import { englishMessages } from '@/core/localization/messages';

import {
  myPhotosRequestErrorPresentation,
  myPhotosUnavailablePresentation,
} from '../my-photos-request-state';

test('maps missing feature routes to an explicit unavailable state without inventing provider success', () => {
  expect(myPhotosRequestErrorPresentation(
    new ApiError('Not found.', 404, 'NOT_FOUND', null),
    englishMessages,
  )).toEqual(myPhotosUnavailablePresentation(englishMessages));
});

test.each([
  new ApiError('Forbidden.', 403, 'MY_PHOTOS_ACCESS_REVOKED', null),
  new ApiError('Gone.', 410, 'GONE', null),
])('maps revoked or expired access to a terminal privacy state', (error) => {
  expect(myPhotosRequestErrorPresentation(error, englishMessages)).toMatchObject({
    tone: 'danger',
    title: englishMessages.myPhotosAccessRevoked(),
    action: 'none',
    busy: false,
  });
});

test.each([
  new TypeError('Network unavailable.'),
  new ApiError('Provider unavailable.', 503, 'MY_PHOTOS_PROVIDER_UNAVAILABLE', null),
  new ApiError('Invalid response.', 502, 'INVALID_RESPONSE', null),
])('keeps transport and contract failures explicit and retryable', (error) => {
  expect(myPhotosRequestErrorPresentation(error, englishMessages)).toMatchObject({
    tone: 'warning',
    title: englishMessages.myPhotosRecoverableError(),
    action: 'refresh',
    busy: false,
  });
});
