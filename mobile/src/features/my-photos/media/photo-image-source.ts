import { base64 } from '@scure/base';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils.js';
import * as Crypto from 'expo-crypto';
import { fetch as expoFetch } from 'expo/fetch';
import { Image, type ImageSource } from 'expo-image';

import { ApiError } from '@/core/api/api-error';
import { authorizedDocumentUrl } from '@/core/api/api-url';
import { assertAuthenticationContextCurrent } from '@/core/api/authentication-context';
import { validateDirectObjectRedirect } from '@/core/api/direct-object-redirect';
import { handleAccessDenied } from '@/core/api/access-denied-handler';
import {
  captureAuthenticationSnapshot,
  type AuthenticationSnapshot,
} from '@/core/auth/session-store';

import {
  isSafeMyPhotosResourcePath,
  type MyPhotosAsset,
} from '../api/contracts';

export type MyPhotosImageVariant = 'thumbnail' | 'preview';

export type MyPhotosImageCacheScope = Readonly<{
  partition: string;
}>;

export type ResolvedMyPhotosImage = Readonly<{
  expiresAtMs: number;
  source: ImageSource;
}>;

export type MyPhotosImageSourceResolver = (
  asset: MyPhotosAsset,
  signal?: AbortSignal,
) => Promise<ResolvedMyPhotosImage | null>;

export type MyPhotosRemoteImageResolver = Readonly<{
  clear(): Promise<void>;
  resolve(
    asset: MyPhotosAsset,
    variant: MyPhotosImageVariant,
    signal?: AbortSignal,
  ): Promise<ResolvedMyPhotosImage | null>;
}>;

const MAX_MEMORY_ENTRIES = 192;
const MAX_CONCURRENT_IMAGE_API_REQUESTS = 6;
const EXPIRY_SKEW_MS = 5_000;
const DIRECT_RESPONSE_MAX_BYTES: Record<MyPhotosImageVariant, number> = {
  thumbnail: 2 * 1024 * 1024,
  preview: 10 * 1024 * 1024,
};
const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

type ImageRequestSlotWaiter = {
  readonly signal: AbortSignal;
  readonly resolve: (release: () => void) => void;
  readonly reject: (error: unknown) => void;
  onAbort: () => void;
};

let activeImageApiRequests = 0;
const imageRequestSlotQueue: ImageRequestSlotWaiter[] = [];

function abortReason(signal: AbortSignal): Error {
  return signal.reason instanceof Error
    ? signal.reason
    : new DOMException('The photo preview request was cancelled.', 'AbortError');
}

function drainImageRequestSlotQueue(): void {
  while (
    activeImageApiRequests < MAX_CONCURRENT_IMAGE_API_REQUESTS
    && imageRequestSlotQueue.length > 0
  ) {
    const waiter = imageRequestSlotQueue.shift();
    if (!waiter) return;
    waiter.signal.removeEventListener('abort', waiter.onAbort);
    if (waiter.signal.aborted) {
      waiter.reject(abortReason(waiter.signal));
      continue;
    }
    activeImageApiRequests += 1;
    let released = false;
    waiter.resolve(() => {
      if (released) return;
      released = true;
      activeImageApiRequests = Math.max(0, activeImageApiRequests - 1);
      drainImageRequestSlotQueue();
    });
  }
}

function acquireImageRequestSlot(signal: AbortSignal): Promise<() => void> {
  if (signal.aborted) return Promise.reject(abortReason(signal));
  return new Promise((resolve, reject) => {
    const waiter: ImageRequestSlotWaiter = {
      signal,
      resolve,
      reject,
      onAbort: () => undefined,
    };
    waiter.onAbort = () => {
      const index = imageRequestSlotQueue.indexOf(waiter);
      if (index >= 0) imageRequestSlotQueue.splice(index, 1);
      reject(abortReason(signal));
    };
    signal.addEventListener('abort', waiter.onAbort, { once: true });
    imageRequestSlotQueue.push(waiter);
    drainImageRequestSlotQueue();
  });
}

function awaitWithCallerAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortReason(signal));
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener('abort', onAbort);
      reject(abortReason(signal));
    };
    signal.addEventListener('abort', onAbort, { once: true });
    void promise.then(
      (value) => {
        signal.removeEventListener('abort', onAbort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener('abort', onAbort);
        reject(error);
      },
    );
  });
}

function authenticationPartition(authentication: AuthenticationSnapshot & { accessToken: string }): string {
  return bytesToHex(sha256(utf8ToBytes(
    `${authentication.epoch}\0${authentication.accessToken}`,
  )));
}

export function createMyPhotosImageCacheScope(
  namespace: string,
  passengerId: string,
): MyPhotosImageCacheScope {
  if (!namespace || !passengerId || namespace.length > 512 || passengerId.length > 128) {
    throw new Error('Invalid My Photos image cache scope.');
  }
  return {
    partition: bytesToHex(sha256(utf8ToBytes(`${namespace}\0${passengerId}`))),
  };
}

function descriptorRequest(
  groupId: string,
  asset: MyPhotosAsset,
  variant: MyPhotosImageVariant,
  cacheScope: MyPhotosImageCacheScope,
): Readonly<{ apiUrl: string; cacheKey: string; descriptorExpiresAtMs: number | null }> | null {
  const descriptor = asset[variant];
  if (descriptor.transport === 'development_fixture') return null;
  if (descriptor.transport !== 'authenticated_api' || !descriptor.resource_path) return null;
  if (!/^[0-9a-f]{64}$/.test(cacheScope.partition)) {
    throw new Error('Invalid My Photos image cache partition.');
  }
  const expected = `/api/v1/mobile/trips/${groupId}/my-photos/photos/${asset.asset_id}/content/${variant}`;
  if (descriptor.resource_path !== expected || !isSafeMyPhotosResourcePath(descriptor.resource_path)) {
    return null;
  }
  const parsedExpiry = descriptor.expires_at ? Date.parse(descriptor.expires_at) : Number.NaN;
  return Object.freeze({
    apiUrl: authorizedDocumentUrl(descriptor.resource_path),
    cacheKey: `my-photos:${cacheScope.partition}:${groupId}:${asset.asset_id}:${variant}:${descriptor.cache_key}`,
    descriptorExpiresAtMs: Number.isFinite(parsedExpiry) ? parsedExpiry : null,
  });
}

async function boundedDataSource(
  response: Awaited<ReturnType<typeof expoFetch>>,
  variant: MyPhotosImageVariant,
  cacheKey: string,
): Promise<ImageSource> {
  const contentType = (response.headers.get('content-type') ?? '').split(';', 1)[0]?.trim().toLowerCase();
  const lengthText = response.headers.get('content-length') ?? '';
  const maximumBytes = DIRECT_RESPONSE_MAX_BYTES[variant];
  if (
    !ALLOWED_IMAGE_TYPES.has(contentType ?? '')
    || !/^\d+$/.test(lengthText)
    || Number(lengthText) < 1
    || Number(lengthText) > maximumBytes
    || !response.body
  ) {
    await response.body?.cancel().catch(() => undefined);
    throw new ApiError('The photo preview response was invalid.', 502, 'INVALID_MEDIA_RESPONSE', null);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      if (!next.value) continue;
      received += next.value.byteLength;
      if (received > maximumBytes || received > Number(lengthText)) {
        throw new ApiError('The photo preview response was invalid.', 502, 'INVALID_MEDIA_RESPONSE', null);
      }
      chunks.push(next.value);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  if (received !== Number(lengthText)) {
    throw new ApiError('The photo preview response was invalid.', 502, 'INVALID_MEDIA_RESPONSE', null);
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return Object.freeze({
    uri: `data:${contentType};base64,${base64.encode(bytes)}`,
    headers: Object.freeze({}),
    cacheKey,
  });
}

export function createMyPhotosRemoteImageResolver(
  groupId: string,
  cacheScope: MyPhotosImageCacheScope,
): MyPhotosRemoteImageResolver {
  const entries = new Map<string, ResolvedMyPhotosImage>();
  const inFlight = new Map<string, Readonly<{
    controller: AbortController;
    promise: Promise<ResolvedMyPhotosImage>;
  }>>();
  let generation = 0;

  async function resolveFresh(
    request: NonNullable<ReturnType<typeof descriptorRequest>> & Readonly<{
      operationKey: string;
      variant: MyPhotosImageVariant;
    }>,
    authentication: AuthenticationSnapshot & { accessToken: string },
    activeGeneration: number,
    controller: AbortController,
  ): Promise<ResolvedMyPhotosImage> {
    const timeout = AbortSignal.timeout(15_000);
    const signal = AbortSignal.any([controller.signal, timeout]);
    const releaseSlot = await acquireImageRequestSlot(signal);
    try {
      let response: Awaited<ReturnType<typeof expoFetch>>;
      try {
        response = await expoFetch(request.apiUrl, {
          method: 'GET',
          credentials: 'omit',
          redirect: 'manual',
          signal,
          headers: {
            Accept: 'image/jpeg,image/png,image/webp',
            Authorization: `Bearer ${authentication.accessToken}`,
            'Cache-Control': 'no-store',
            'X-Request-ID': Crypto.randomUUID(),
          },
        });
      } catch (error) {
        assertAuthenticationContextCurrent(authentication);
        throw error;
      }
      assertAuthenticationContextCurrent(authentication);

      let resolved: ResolvedMyPhotosImage;
      let cacheInMemory = false;
      if (response.status === 307) {
        const location = response.headers.get('location');
        await response.body?.cancel().catch(() => undefined);
        const direct = validateDirectObjectRedirect(
          request.apiUrl,
          location,
          response.headers.get('x-gc-media-expires-at'),
        );
        const expiresAtMs = Math.min(
          direct.expiresAtMs,
          request.descriptorExpiresAtMs ?? direct.expiresAtMs,
        ) - EXPIRY_SKEW_MS;
        if (expiresAtMs <= Date.now()) {
          throw new ApiError('The photo delivery redirect was invalid.', 502, 'PHOTO_DELIVERY_REDIRECT_INVALID', null);
        }
        resolved = Object.freeze({
          expiresAtMs,
          source: Object.freeze({
            uri: direct.url,
            headers: Object.freeze({}),
            cacheKey: request.cacheKey,
          }),
        });
        cacheInMemory = true;
      } else if (response.status === 200) {
        const source = await boundedDataSource(response, request.variant, request.cacheKey);
        assertAuthenticationContextCurrent(authentication);
        resolved = Object.freeze({
          expiresAtMs: Math.min(
            Date.now() + 60_000,
            request.descriptorExpiresAtMs ?? Number.POSITIVE_INFINITY,
          ),
          source,
        });
        // Development fixture bytes are returned once and never retained in
        // the resolver cache; count-only URL LRU accounting is not a byte cap.
      } else {
        await response.body?.cancel().catch(() => undefined);
        await handleAccessDenied(new URL(request.apiUrl).pathname, response.status);
        assertAuthenticationContextCurrent(authentication);
        throw new ApiError('The photo preview is unavailable.', response.status, `HTTP_${response.status}`, null);
      }

      if (signal.aborted) throw abortReason(signal);
      assertAuthenticationContextCurrent(authentication);
      if (cacheInMemory && activeGeneration === generation) {
        while (entries.size >= MAX_MEMORY_ENTRIES) {
          const oldest = entries.keys().next().value;
          if (typeof oldest !== 'string') break;
          entries.delete(oldest);
        }
        entries.set(request.operationKey, resolved);
      }
      return resolved;
    } finally {
      releaseSlot();
    }
  }

  return Object.freeze({
    async clear(): Promise<void> {
      generation += 1;
      entries.clear();
      for (const active of inFlight.values()) active.controller.abort();
      inFlight.clear();
      // Remote My Photos images use cachePolicy="memory". Purge the native
      // decoded-image cache at the screen/auth boundary so a later account
      // cannot reuse a private bitmap. Disk cache is intentionally untouched.
      try {
        await Image.clearMemoryCache();
      } catch {
        // Best effort on teardown; the resolver generation still prevents any
        // in-flight result from being republished into this account boundary.
      }
    },

    async resolve(
      asset: MyPhotosAsset,
      variant: MyPhotosImageVariant,
      callerSignal?: AbortSignal,
    ): Promise<ResolvedMyPhotosImage | null> {
      const request = descriptorRequest(groupId, asset, variant, cacheScope);
      if (!request) return null;
      if (callerSignal?.aborted) throw abortReason(callerSignal);
      const authentication = captureAuthenticationSnapshot();
      if (!authentication.accessToken) return null;
      const operationKey = `${request.cacheKey}:auth:${authenticationPartition(
        authentication as AuthenticationSnapshot & { accessToken: string },
      )}`;
      const boundedRequest = Object.freeze({ ...request, operationKey, variant });
      const cached = entries.get(operationKey);
      if (cached && cached.expiresAtMs > Date.now() + EXPIRY_SKEW_MS) {
        entries.delete(operationKey);
        entries.set(operationKey, cached);
        return cached;
      }
      entries.delete(operationKey);
      let active = inFlight.get(operationKey);
      if (!active) {
        const controller = new AbortController();
        const record = {} as {
          controller: AbortController;
          promise: Promise<ResolvedMyPhotosImage>;
        };
        record.controller = controller;
        record.promise = resolveFresh(
          boundedRequest,
          authentication as AuthenticationSnapshot & { accessToken: string },
          generation,
          controller,
        ).finally(() => {
          if (inFlight.get(operationKey) === record) inFlight.delete(operationKey);
        });
        active = record;
        inFlight.set(operationKey, active);
      }
      return awaitWithCallerAbort(active.promise, callerSignal);
    },
  });
}
