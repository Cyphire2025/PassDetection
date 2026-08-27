import {
  DownloadAuthorizationResponseSchema,
  MyPhotosDownloadPlanSchema,
} from '../contracts';
import { MY_PHOTOS_MAX_ITEM_BYTES } from '../../limits';
import { myPhotosDownloadContentPath } from '../my-photos-api';

const plan = {
  snapshot_revision: 3,
  matched_item_count: 57,
  downloadable_item_count: 55,
  preparing_item_count: 2,
  qualities: [
    {
      quality: 'original',
      supported_item_count: 57,
      exact_byte_total: 570_000_000,
      maximum_item_bytes: 12_000_000,
      estimate_complete: true,
    },
    {
      quality: 'optimized',
      supported_item_count: 57,
      exact_byte_total: 114_000_000,
      maximum_item_bytes: 3_000_000,
      estimate_complete: true,
    },
  ],
};

describe('My Photos download contracts', () => {
  it('derives the exact authorization route for production object delivery', () => {
    expect(myPhotosDownloadContentPath(
      '33333333-3333-4333-8333-333333333333',
      '44444444-4444-4444-8444-444444444444',
    )).toBe(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content',
    );
    expect(() => myPhotosDownloadContentPath(
      '33333333-3333-4333-8333-333333333333',
      '../provider-object',
    )).toThrow('Download authorization must be a UUID');
  });

  it('accepts the exact aggregate required for bounded Download All preflight', () => {
    expect(MyPhotosDownloadPlanSchema.parse(plan)).toEqual(plan);
  });

  it('rejects incomplete, duplicated, contradictory, and permissive plan shapes', () => {
    expect(() => MyPhotosDownloadPlanSchema.parse({
      ...plan,
      qualities: [plan.qualities[0], plan.qualities[0]],
    })).toThrow();
    expect(() => MyPhotosDownloadPlanSchema.parse({
      ...plan,
      qualities: [plan.qualities[0], { ...plan.qualities[1], estimate_complete: false }],
    })).toThrow();
    expect(() => MyPhotosDownloadPlanSchema.parse({ ...plan, unexpected: true })).toThrow();
    expect(() => MyPhotosDownloadPlanSchema.parse({
      ...plan,
      qualities: [
        { ...plan.qualities[0], maximum_item_bytes: MY_PHOTOS_MAX_ITEM_BYTES + 1 },
        plan.qualities[1],
      ],
    })).toThrow();
  });

  it('requires a positive stable content delivery version in every authorization state', () => {
    const unavailable = {
      authorizations: [{
        asset_id: '11111111-1111-4111-8111-111111111111',
        authorization_id: null,
        quality: 'original',
        delivery_version: 4,
        state: 'unavailable',
        transport: 'unavailable',
        resource_path: null,
        content_type: null,
        expected_size_bytes: null,
        checksum_sha256: null,
        supports_ranges: false,
        expires_at: null,
        retry_after_seconds: 60,
      }],
    };
    expect(DownloadAuthorizationResponseSchema.parse(unavailable)).toEqual(unavailable);
    expect(() => DownloadAuthorizationResponseSchema.parse({
      authorizations: [{ ...unavailable.authorizations[0], delivery_version: 0 }],
    })).toThrow();
  });

  it('fails closed for HEIC originals until the native vault and export path support them', () => {
    expect(() => DownloadAuthorizationResponseSchema.parse({
      authorizations: [{
        asset_id: '11111111-1111-4111-8111-111111111111',
        authorization_id: '22222222-2222-4222-8222-222222222222',
        quality: 'original',
        delivery_version: 1,
        state: 'available',
        transport: 'development_fixture',
        resource_path: '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download',
        content_type: 'image/heic',
        expected_size_bytes: 1024,
        checksum_sha256: 'a'.repeat(64),
        supports_ranges: true,
        expires_at: '2026-08-23T12:00:00.000Z',
        retry_after_seconds: null,
      }],
    })).toThrow();
  });

  it('rejects authorization metadata above the vault item ceiling', () => {
    const available = {
      asset_id: '11111111-1111-4111-8111-111111111111',
      authorization_id: '22222222-2222-4222-8222-222222222222',
      quality: 'original',
      delivery_version: 1,
      state: 'available',
      transport: 'direct_object_storage',
      resource_path: null,
      content_type: 'image/jpeg',
      expected_size_bytes: MY_PHOTOS_MAX_ITEM_BYTES,
      checksum_sha256: 'a'.repeat(64),
      supports_ranges: true,
      expires_at: '2026-08-23T12:00:00.000Z',
      retry_after_seconds: null,
    };
    expect(DownloadAuthorizationResponseSchema.parse({ authorizations: [available] }))
      .toEqual({ authorizations: [available] });
    expect(() => DownloadAuthorizationResponseSchema.parse({
      authorizations: [{
        ...available,
        expected_size_bytes: MY_PHOTOS_MAX_ITEM_BYTES + 1,
      }],
    })).toThrow();
  });
});
