import { englishMessages } from '@/core/localization/messages';

import type { FaceScanFailure } from '../../model/face-scan-machine';
import {
  faceScanFailureBodyCopy,
  faceScanFailureCopy,
} from '../face-scan-failure-copy';

const FAILURES: readonly FaceScanFailure[] = [
  'camera_denied',
  'camera_blocked',
  'camera_unavailable',
  'front_camera_unavailable',
  'no_face',
  'multiple_faces',
  'face_too_close',
  'face_too_far',
  'poor_lighting',
  'excessive_movement',
  'network_interrupted',
  'session_expired',
  'liveness_rejected',
  'provider_timeout',
  'provider_unavailable',
  'rate_limited',
  'device_unsupported',
  'cancelled',
  'backgrounded',
  'nonrecoverable',
];

test.each(FAILURES)('Face Scan failure %s has explicit reviewed recovery copy', (failure) => {
  const copy = faceScanFailureCopy(failure, englishMessages);
  expect(copy.trim()).not.toBe('');
  expect(copy).not.toBe(englishMessages.myPhotosRecoverableError());
});

test('no-face and multiple-face failures never imply that a largest face was accepted', () => {
  expect(faceScanFailureCopy('no_face', englishMessages)).toContain('No usable face');
  expect(faceScanFailureCopy('multiple_faces', englishMessages)).toContain('More than one face');
});

test('unsupported devices receive terminal guidance rather than retry-session copy', () => {
  expect(faceScanFailureBodyCopy('device_unsupported', englishMessages)).toContain('supported device');
  expect(faceScanFailureBodyCopy('device_unsupported', englishMessages))
    .not.toBe(englishMessages.myPhotosRetryNewSession());
});
