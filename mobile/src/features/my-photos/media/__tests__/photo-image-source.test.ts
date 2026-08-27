import { fetch as expoFetch } from 'expo/fetch';
import { Image } from 'expo-image';

import { ApiError } from '@/core/api/api-error';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import type { MyPhotosAsset } from '../../api/contracts';
import {
  createMyPhotosImageCacheScope,
  createMyPhotosRemoteImageResolver,
} from '../photo-image-source';

jest.mock('@/core/config/env', () => ({
  env: { apiUrl: 'https://api.example.com/api/v1', appEnv: 'production' },
}));
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('expo-image', () => ({
  Image: {
    clearDiskCache: jest.fn(),
    clearMemoryCache: jest.fn(),
  },
}));
jest.mock('expo-crypto', () => ({ randomUUID: () => '55555555-5555-4555-8555-555555555555' }));

const mockedExpoFetch = jest.mocked(expoFetch);
const mockedClearDiskCache = jest.mocked(Image.clearDiskCache);
const mockedClearMemoryCache = jest.mocked(Image.clearMemoryCache);
const groupId = '2c426a87-fcad-4ddb-b57b-5d34ee56aa4e';
const assetId = '22f145f8-f648-4e7d-82b3-54de221fbc6f';
const namespace = '48a7b50b-c513-49bc-a3c6-bffbc8b984cb.a2fc9442-1434-4ba0-bd7e-5d4710160420';
const passengerId = '66ca080d-44dd-4b5c-908f-1d965c65b8a1';
const cacheScope = createMyPhotosImageCacheScope(namespace, passengerId);
const descriptor = {
  state: 'preview_available' as const,
  transport: 'authenticated_api' as const,
  cache_key: 'revision:2:thumbnail',
  max_width: 480,
  max_height: 480,
  resource_path: `/api/v1/mobile/trips/${groupId}/my-photos/photos/${assetId}/content/thumbnail`,
  authorization_id: null,
  expires_at: null,
};
const asset = {
  asset_id: assetId,
  thumbnail: descriptor,
  preview: {
    ...descriptor,
    cache_key: 'revision:2:preview',
    resource_path: descriptor.resource_path.replace('thumbnail', 'preview'),
  },
} as MyPhotosAsset;

function assetWithId(id: string, revision: number): MyPhotosAsset {
  const resourceRoot = `/api/v1/mobile/trips/${groupId}/my-photos/photos/${id}/content`;
  return {
    ...asset,
    asset_id: id,
    thumbnail: {
      ...descriptor,
      cache_key: `revision:${revision}:thumbnail`,
      resource_path: `${resourceRoot}/thumbnail`,
    },
    preview: {
      ...descriptor,
      cache_key: `revision:${revision}:preview`,
      resource_path: `${resourceRoot}/preview`,
    },
  } as MyPhotosAsset;
}

async function flushRequestQueue(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

const session: MobileSession = {
  accessToken: 'secret-token',
  accessTokenExpiresAt: new Date(Date.now() + 60_000).toISOString(),
  refreshTokenExpiresAt: new Date(Date.now() + 120_000).toISOString(),
  sessionId: 'session-id',
  networkMode: 'online',
  principal: {
    id: '11111111-1111-4111-8111-111111111111',
    accountId: '11111111-1111-4111-8111-111111111111',
    principalType: 'passenger',
    agencyId: '22222222-2222-4222-8222-222222222222',
    passengerId,
    displayName: 'Passenger',
    email: null,
    phoneNumber: '+919999999999',
    forcePasswordChange: false,
  },
};

function redirectResponse(
  location: string,
  expiresAt = new Date(Date.now() + 5 * 60_000).toISOString(),
): Awaited<ReturnType<typeof expoFetch>> {
  return {
    body: new ReadableStream<Uint8Array>(),
    headers: new Headers({
      location,
      'x-gc-media-expires-at': expiresAt,
    }),
    status: 307,
  } as Awaited<ReturnType<typeof expoFetch>>;
}

describe('My Photos authenticated image resolution', () => {
  beforeEach(() => {
    useSessionStore.getState().setSession(session);
    mockedExpoFetch.mockReset();
    mockedClearDiskCache.mockReset();
    mockedClearMemoryCache.mockReset();
    mockedClearMemoryCache.mockResolvedValue(false);
  });

  afterEach(() => {
    useSessionStore.getState().clear();
    jest.restoreAllMocks();
  });

  it('authenticates only the API hop and returns an opaque direct source with no custom headers', async () => {
    const signedUrl = 'https://gc-photos.s3.ap-south-1.amazonaws.com/private/photo.jpg?provider-fields=opaque';
    mockedExpoFetch.mockResolvedValue(redirectResponse(signedUrl));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);

    const result = await resolver.resolve(asset, 'thumbnail');

    expect(mockedExpoFetch).toHaveBeenCalledTimes(1);
    expect(mockedExpoFetch).toHaveBeenCalledWith(
      `https://api.example.com${descriptor.resource_path}`,
      expect.objectContaining({
        credentials: 'omit',
        redirect: 'manual',
        headers: expect.objectContaining({
          Authorization: 'Bearer secret-token',
          'X-Request-ID': '55555555-5555-4555-8555-555555555555',
        }),
      }),
    );
    expect(result?.source).toEqual({
      uri: signedUrl,
      headers: {},
      cacheKey: expect.stringMatching(
        new RegExp(`^my-photos:[0-9a-f]{64}:${groupId}:${assetId}:thumbnail:revision:2:thumbnail$`),
      ),
    });
    expect(result?.source.headers).not.toEqual(expect.objectContaining({
      Authorization: expect.anything(),
      'X-GC-Download-Token': expect.anything(),
      'X-Request-ID': expect.anything(),
    }));
    expect(result?.source.cacheKey).not.toContain(namespace);
    expect(result?.source.cacheKey).not.toContain(passengerId);
    expect(result?.source.cacheKey).not.toContain(signedUrl);
    await resolver.clear();
    expect(mockedClearMemoryCache).toHaveBeenCalledTimes(1);
    expect(mockedClearDiskCache).not.toHaveBeenCalled();
  });

  it('keeps a resolved URL only in its bounded memory cache and clears it explicitly', async () => {
    const signedUrl = 'https://objects.example.test/photo.jpg?opaque=one';
    mockedExpoFetch.mockResolvedValue(redirectResponse(signedUrl));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);

    await expect(resolver.resolve(asset, 'preview')).resolves.toMatchObject({
      source: { uri: signedUrl, headers: {} },
    });
    await expect(resolver.resolve(asset, 'preview')).resolves.toMatchObject({
      source: { uri: signedUrl, headers: {} },
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(1);

    await resolver.clear();
    await resolver.resolve(asset, 'preview');
    expect(mockedExpoFetch).toHaveBeenCalledTimes(2);
    expect(mockedClearMemoryCache).toHaveBeenCalledTimes(1);
    expect(mockedClearDiskCache).not.toHaveBeenCalled();
  });

  it('coalesces concurrent requests for the same authenticated asset revision', async () => {
    const releases: ((response: Awaited<ReturnType<typeof expoFetch>>) => void)[] = [];
    mockedExpoFetch.mockImplementation(() => new Promise((resolve) => {
      releases.push(resolve);
    }));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);
    const first = resolver.resolve(asset, 'thumbnail');
    const second = resolver.resolve(asset, 'thumbnail');
    await flushRequestQueue();

    expect(mockedExpoFetch).toHaveBeenCalledTimes(1);
    releases[0]?.(redirectResponse('https://objects.example.test/photo.jpg?opaque=coalesced'));
    const [firstResult, secondResult] = await Promise.all([first, second]);
    expect(firstResult).toBe(secondResult);
    await resolver.clear();
  });

  it('limits authenticated image API fan-out to six concurrent requests', async () => {
    const releases: ((response: Awaited<ReturnType<typeof expoFetch>>) => void)[] = [];
    let activeRequests = 0;
    let maximumActiveRequests = 0;
    mockedExpoFetch.mockImplementation(() => new Promise((resolve) => {
      activeRequests += 1;
      maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
      releases.push((response) => {
        activeRequests -= 1;
        resolve(response);
      });
    }));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);
    const assets = Array.from({ length: 8 }, (_value, index) => assetWithId(
      `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      index + 1,
    ));
    const requests = assets.map((item) => resolver.resolve(item, 'thumbnail'));
    await flushRequestQueue();

    expect(mockedExpoFetch).toHaveBeenCalledTimes(6);
    expect(maximumActiveRequests).toBe(6);
    releases[0]?.(redirectResponse('https://objects.example.test/photo-0.jpg?opaque=0'));
    await requests[0];
    await flushRequestQueue();
    expect(mockedExpoFetch).toHaveBeenCalledTimes(7);
    for (let index = 1; index < 6; index += 1) {
      releases[index]?.(redirectResponse(`https://objects.example.test/photo-${index}.jpg?opaque=${index}`));
    }
    await Promise.all(requests.slice(1, 6));
    await flushRequestQueue();
    expect(mockedExpoFetch).toHaveBeenCalledTimes(8);
    releases[6]?.(redirectResponse('https://objects.example.test/photo-6.jpg?opaque=6'));
    releases[7]?.(redirectResponse('https://objects.example.test/photo-7.jpg?opaque=7'));
    await Promise.all(requests.slice(6));
    expect(maximumActiveRequests).toBe(6);
    await resolver.clear();
  });

  it('lets one coalesced waiter abort without cancelling another waiter', async () => {
    const releases: ((response: Awaited<ReturnType<typeof expoFetch>>) => void)[] = [];
    mockedExpoFetch.mockImplementation(() => new Promise((resolve) => {
      releases.push(resolve);
    }));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);
    const firstController = new AbortController();
    const secondController = new AbortController();
    const first = resolver.resolve(asset, 'thumbnail', firstController.signal);
    const second = resolver.resolve(asset, 'thumbnail', secondController.signal);
    await flushRequestQueue();

    firstController.abort();
    await expect(first).rejects.toMatchObject({ name: 'AbortError' });
    releases[0]?.(redirectResponse('https://objects.example.test/photo.jpg?opaque=remaining-waiter'));
    await expect(second).resolves.toMatchObject({
      source: { uri: 'https://objects.example.test/photo.jpg?opaque=remaining-waiter' },
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(1);
    await resolver.clear();
  });

  it('aborts active work and prevents a post-clear cache insertion', async () => {
    const releases: ((response: Awaited<ReturnType<typeof expoFetch>>) => void)[] = [];
    mockedExpoFetch.mockImplementation(() => new Promise((resolve) => {
      releases.push(resolve);
    }));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);
    const staleRequest = resolver.resolve(asset, 'thumbnail');
    await flushRequestQueue();
    await resolver.clear();
    releases[0]?.(redirectResponse('https://objects.example.test/photo.jpg?opaque=stale'));
    await expect(staleRequest).rejects.toMatchObject({ name: 'AbortError' });

    mockedExpoFetch.mockResolvedValueOnce(
      redirectResponse('https://objects.example.test/photo.jpg?opaque=fresh'),
    );
    await expect(resolver.resolve(asset, 'thumbnail')).resolves.toMatchObject({
      source: { uri: 'https://objects.example.test/photo.jpg?opaque=fresh' },
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(2);
    await resolver.clear();
  });

  it.each([
    ['non-HTTPS', 'http://objects.example.test/photo.jpg', undefined],
    ['same-origin', 'https://api.example.com/private/photo.jpg', undefined],
    ['userinfo', 'https://user:password@objects.example.test/photo.jpg', undefined],
    ['fragment', 'https://objects.example.test/photo.jpg#secret', undefined],
    ['missing expiry', 'https://objects.example.test/photo.jpg', ''],
    ['expired', 'https://objects.example.test/photo.jpg', new Date(Date.now() - 1_000).toISOString()],
    ['overlong expiry', 'https://objects.example.test/photo.jpg', new Date(Date.now() + 901_000).toISOString()],
  ])('fails closed for a %s redirect', async (_label, location, expiresAt) => {
    mockedExpoFetch.mockResolvedValue(redirectResponse(location, expiresAt));
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);

    await expect(resolver.resolve(asset, 'thumbnail')).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PHOTO_DELIVERY_REDIRECT_INVALID',
      status: 502,
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(1);
  });

  it('does not parse provider-specific signature query fields', async () => {
    const opaqueUrl = 'https://objects.example.test/photo.jpg?X-Amz-Date=not-a-date&X-Amz-Expires=not-a-number';
    mockedExpoFetch.mockResolvedValue(redirectResponse(opaqueUrl));

    await expect(
      createMyPhotosRemoteImageResolver(groupId, cacheScope).resolve(asset, 'thumbnail'),
    ).resolves.toMatchObject({ source: { uri: opaqueUrl, headers: {} } });
  });

  it('supports the authenticated development fixture response without persistent caching', async () => {
    const bytes = Uint8Array.from([1, 2, 3, 4]);
    mockedExpoFetch.mockImplementation(async () => ({
        body: new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(bytes);
            controller.close();
          },
        }),
        headers: new Headers({
          'content-length': String(bytes.byteLength),
          'content-type': 'image/png',
        }),
        status: 200,
      } as Awaited<ReturnType<typeof expoFetch>>));

    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);

    await expect(
      resolver.resolve(asset, 'thumbnail'),
    ).resolves.toMatchObject({
      source: {
        uri: 'data:image/png;base64,AQIDBA==',
        headers: {},
      },
    });
    await expect(resolver.resolve(asset, 'thumbnail')).resolves.toMatchObject({
      source: { uri: 'data:image/png;base64,AQIDBA==' },
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(2);
    await resolver.clear();
  });

  it('partitions decoded image caches by trusted account and passenger scope', () => {
    const first = cacheScope.partition;
    const otherAccount = createMyPhotosImageCacheScope(
      'a-different-account-namespace',
      passengerId,
    ).partition;
    const otherPassenger = createMyPhotosImageCacheScope(
      namespace,
      '514d3d60-177c-4b94-977c-3f970020d022',
    ).partition;
    expect(first).not.toBe(otherAccount);
    expect(first).not.toBe(otherPassenger);
    expect(first).not.toContain(namespace);
    expect(first).not.toContain(passengerId);
  });

  it('does not collapse account locators that collide under the prior 32-bit partition', () => {
    // "costarring" and "liquid" are an FNV-1a 32-bit collision.
    expect(createMyPhotosImageCacheScope('costarring', passengerId).partition).not.toBe(
      createMyPhotosImageCacheScope('liquid', passengerId).partition,
    );
  });

  it('fails closed for a mismatched asset route or missing active token', async () => {
    const resolver = createMyPhotosRemoteImageResolver(groupId, cacheScope);
    await expect(resolver.resolve(
      { ...asset, asset_id: '89009161-7fe8-4d75-94c9-5d8ccce2f326' },
      'thumbnail',
    )).resolves.toBeNull();
    useSessionStore.getState().clear();
    await expect(resolver.resolve(asset, 'thumbnail')).resolves.toBeNull();
    expect(mockedExpoFetch).not.toHaveBeenCalled();
  });
});
