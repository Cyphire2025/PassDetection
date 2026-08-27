import { isSafeMyPhotosResourcePath, MediaVariantDescriptorSchema } from '../contracts';

describe('My Photos media resource boundary', () => {
  it('accepts only a canonical authenticated mobile resource path', () => {
    expect(isSafeMyPhotosResourcePath(
      '/api/v1/mobile/trips/2c426a87-fcad-4ddb-b57b-5d34ee56aa4e/my-photos/photos/22f145f8-f648-4e7d-82b3-54de221fbc6f/content/thumbnail',
    )).toBe(true);
  });

  it.each([
    '/api/v1/mobile/../admin',
    '/api/v1/mobile/%2e%2e/admin',
    '/api/v1/mobile/%2Fadmin',
    '/api/v1/mobile/%5cadmin',
    '/api/v1/mobile//admin',
    '/api/v1/mobile/resource?redirect=https://evil.example',
    '/api/v1/mobile/resource#token',
    'https://evil.example/api/v1/mobile/resource',
  ])('rejects unsafe resource %s', (path) => {
    expect(isSafeMyPhotosResourcePath(path)).toBe(false);
  });

  it('rejects any delivery material on an unavailable or local development fixture', () => {
    const common = {
      state: 'preview_available',
      cache_key: 'asset:thumbnail:v1',
      max_width: 480,
      max_height: 480,
      authorization_id: null,
      expires_at: null,
    } as const;
    expect(MediaVariantDescriptorSchema.safeParse({
      ...common,
      transport: 'unavailable',
      resource_path: '/api/v1/mobile/resource',
    }).success).toBe(false);
    expect(MediaVariantDescriptorSchema.safeParse({
      ...common,
      transport: 'development_fixture',
      resource_path: '/api/v1/mobile/resource',
    }).success).toBe(false);
  });
});
