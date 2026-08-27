import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { fetch as expoFetch } from 'expo/fetch';

import {
  ApiError,
  apiDownloadToFile,
  authorizedDownloadToFile,
  registerAccessDeniedHandler,
  withAuthorizedDownloadStream,
} from '../client';
import { authorizedDocumentUrl } from '../api-url';
import { downloadNativeFileBounded } from '../native-file-download';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('../native-file-download', () => {
  const actual = jest.requireActual('../native-file-download');
  return { ...actual, downloadNativeFileBounded: jest.fn() };
});

const mockedNativeDownload = jest.mocked(downloadNativeFileBounded);
const mockedExpoFetch = jest.mocked(expoFetch);
const downloadAuthorizationPath = '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content';
const sameOriginRedirect = `${new URL(authorizedDocumentUrl(downloadAuthorizationPath)).origin}/private/photo.jpg?signature=secret`;

const session: MobileSession = {
  accessToken: 'mobile-access-token',
  accessTokenExpiresAt: new Date(Date.now() + 60_000).toISOString(),
  refreshTokenExpiresAt: new Date(Date.now() + 120_000).toISOString(),
  sessionId: 'session-id',
  networkMode: 'online',
  principal: {
    id: '11111111-1111-4111-8111-111111111111',
    accountId: '11111111-1111-4111-8111-111111111111',
    principalType: 'passenger',
    agencyId: '22222222-2222-4222-8222-222222222222',
    displayName: 'Passenger',
    email: null,
    phoneNumber: '+919999999999',
    forcePasswordChange: false,
  },
};

describe('authorized document resume requests', () => {
  beforeEach(() => {
    useSessionStore.getState().setSession(session);
    mockedNativeDownload.mockReset();
    mockedExpoFetch.mockReset();
  });

  afterEach(() => {
    useSessionStore.getState().clear();
    jest.restoreAllMocks();
  });

  it('rejects an invalid offset before making a network request', async () => {
    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      4096,
      undefined,
      -1,
    )).rejects.toMatchObject<Partial<ApiError>>({ code: 'INVALID_DOWNLOAD_RANGE', status: 400 });
    expect(mockedNativeDownload).not.toHaveBeenCalled();
  });

  it('streams a resume request to an exact native path without forwarding redirects', async () => {
    mockedNativeDownload.mockResolvedValue({
      headers: {
        'content-length': '2048',
        'content-range': 'bytes 2048-4095/4096',
        'content-type': 'application/pdf',
      },
      redirects: [],
      status: 206,
    });

    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      2048,
      undefined,
      2048,
    )).resolves.toMatchObject({ status: 206 });

    expect(mockedNativeDownload).toHaveBeenCalledWith(expect.objectContaining({
      destinationPath: '/private/cache/download.tmp',
      maximumBytes: 2048,
      headers: expect.objectContaining({
        Authorization: 'Bearer mobile-access-token',
        Range: 'bytes=2048-',
        'X-GC-Download-Token': 'a'.repeat(32),
      }),
    }));
  });

  it('streams an authenticated bounded file without allocating its body in JavaScript', async () => {
    mockedNativeDownload.mockResolvedValue({
      headers: {
        'content-length': '4096',
        'content-type': 'image/jpeg',
      },
      redirects: [],
      status: 200,
    });

    await expect(apiDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      {
        accept: 'image/jpeg',
        destinationPath: '/private/cache/bounded-download.tmp',
        maximumBytes: 4096,
        timeoutMs: 5_000,
      },
    )).resolves.toMatchObject({ status: 200 });

    expect(mockedNativeDownload).toHaveBeenCalledWith(expect.objectContaining({
      destinationPath: '/private/cache/bounded-download.tmp',
      maximumBytes: 4096,
      timeoutMs: 5_000,
      headers: expect.objectContaining({
        Accept: 'image/jpeg',
        Authorization: 'Bearer mobile-access-token',
        'Cache-Control': 'no-store',
      }),
    }));
  });

  it('supports a bounded first range without changing bearer or grant semantics', async () => {
    mockedNativeDownload.mockResolvedValue({
      headers: {
        'content-length': '4096',
        'content-range': 'bytes 0-4095/8192',
        'content-type': 'image/jpeg',
      },
      redirects: [],
      status: 206,
    });

    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      4096,
      undefined,
      0,
      4095,
    )).resolves.toMatchObject({ status: 206 });

    expect(mockedNativeDownload).toHaveBeenCalledWith(expect.objectContaining({
      maximumBytes: 4096,
      headers: expect.objectContaining({
        Authorization: 'Bearer mobile-access-token',
        Range: 'bytes=0-4095',
        'X-GC-Download-Token': 'a'.repeat(32),
      }),
    }));
  });

  it('rejects an inverted or oversized bounded range before native I/O', async () => {
    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      4096,
      undefined,
      4096,
      4095,
    )).rejects.toMatchObject<Partial<ApiError>>({ code: 'INVALID_DOWNLOAD_RANGE', status: 400 });
    await expect(authorizedDownloadToFile(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
      'a'.repeat(32),
      '/private/cache/download.tmp',
      2048,
      undefined,
      0,
      4095,
    )).rejects.toMatchObject<Partial<ApiError>>({ code: 'INVALID_DOWNLOAD_RANGE', status: 400 });
    expect(mockedNativeDownload).not.toHaveBeenCalled();
  });

  it('maps a native 401 to an expired short-lived grant without purging trip access', async () => {
    const accessDenied = jest.fn(async () => undefined);
    const unregister = registerAccessDeniedHandler(accessDenied);
    mockedNativeDownload.mockResolvedValue({ headers: {}, redirects: [], status: 401 });

    try {
      await expect(authorizedDownloadToFile(
        '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/documents/44444444-4444-4444-8444-444444444444/content?version=1',
        'a'.repeat(32),
        '/private/cache/download.tmp',
        4096,
      )).rejects.toMatchObject<Partial<ApiError>>({
        code: 'DOWNLOAD_AUTH_EXPIRED',
        status: 401,
      });
      expect(accessDenied).not.toHaveBeenCalled();
    } finally {
      unregister();
    }
  });

  it('keeps bearer and exact range fencing active while a native response stream is consumed', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(Uint8Array.from([1, 2, 3, 4]));
        controller.close();
      },
    });
    mockedExpoFetch.mockResolvedValue({
      body,
      headers: new Headers({
        'content-length': '4',
        'content-range': 'bytes 8-11/12',
        'content-type': 'image/jpeg',
      }),
      status: 206,
    } as Awaited<ReturnType<typeof expoFetch>>);

    const result = await withAuthorizedDownloadStream(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content',
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 8,
        rangeEndInclusive: 11,
        requestRange: true,
      },
      async (response, assertCurrent) => {
        assertCurrent();
        const reader = response.body.getReader();
        const first = await reader.read();
        const end = await reader.read();
        reader.releaseLock();
        assertCurrent();
        expect(response).toMatchObject({
          status: 206,
          headers: {
            'content-length': '4',
            'content-range': 'bytes 8-11/12',
          },
        });
        expect(end.done).toBe(true);
        return first.value?.byteLength ?? 0;
      },
    );

    expect(result).toBe(4);
    expect(mockedExpoFetch).toHaveBeenCalledWith(
      expect.stringContaining('/my-photos/download-authorizations/'),
      expect.objectContaining({
        redirect: 'manual',
        headers: expect.objectContaining({
          Authorization: 'Bearer mobile-access-token',
          Range: 'bytes=8-11',
          'X-GC-Download-Token': 'a'.repeat(32),
        }),
      }),
    );
  });

  it('follows one validated S3 redirect with a fresh credential-free request', async () => {
    const expiresAt = new Date(Date.now() + 5 * 60_000).toISOString();
    const signedUrl = 'https://gc-photos.s3.ap-south-1.amazonaws.com/private/photo.jpg?' + new URLSearchParams({
      'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
      'X-Amz-Credential': 'temporary-access/20260827/ap-south-1/s3/aws4_request',
      'X-Amz-Date': 'opaque-to-mobile',
      'X-Amz-Expires': '300',
      'X-Amz-Signature': 'a'.repeat(64),
      'X-Amz-SignedHeaders': 'host',
    }).toString();
    const redirectBody = new ReadableStream<Uint8Array>();
    const providerBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(Uint8Array.from([1, 2, 3, 4]));
        controller.close();
      },
    });
    mockedExpoFetch
      .mockResolvedValueOnce({
        body: redirectBody,
        headers: new Headers({ location: signedUrl, 'x-gc-media-expires-at': expiresAt }),
        status: 307,
      } as Awaited<ReturnType<typeof expoFetch>>)
      .mockResolvedValueOnce({
        body: providerBody,
        headers: new Headers({
          'content-length': '4',
          'content-range': 'bytes 8-11/12',
          'content-type': 'image/jpeg',
        }),
        status: 206,
      } as Awaited<ReturnType<typeof expoFetch>>);

    await expect(withAuthorizedDownloadStream(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content',
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 8,
        rangeEndInclusive: 11,
        requestRange: true,
      },
      async (response) => response.status,
    )).resolves.toBe(206);

    expect(mockedExpoFetch).toHaveBeenCalledTimes(2);
    expect(mockedExpoFetch.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      redirect: 'manual',
      headers: expect.objectContaining({
        Authorization: 'Bearer mobile-access-token',
        'X-GC-Download-Token': 'a'.repeat(32),
      }),
    }));
    const providerRequest = mockedExpoFetch.mock.calls[1];
    expect(providerRequest?.[0]).toBe(signedUrl);
    expect(providerRequest?.[1]).toEqual(expect.objectContaining({
      credentials: 'omit',
      redirect: 'error',
      headers: {
        Accept: 'image/jpeg,image/png,image/webp',
        'Cache-Control': 'no-store',
        Range: 'bytes=8-11',
      },
    }));
    expect(providerRequest?.[1]?.headers).not.toEqual(expect.objectContaining({
      Authorization: expect.anything(),
      'X-GC-Download-Token': expect.anything(),
      'X-Request-ID': expect.anything(),
    }));
  });

  it('fails closed when the provider response attempts a second redirect', async () => {
    const signedUrl = 'https://gc-photos.s3.ap-south-1.amazonaws.com/private/photo.jpg?opaque=first-hop';
    mockedExpoFetch
      .mockResolvedValueOnce({
        body: new ReadableStream<Uint8Array>(),
        headers: new Headers({
          location: signedUrl,
          'x-gc-media-expires-at': new Date(Date.now() + 5 * 60_000).toISOString(),
        }),
        status: 307,
      } as Awaited<ReturnType<typeof expoFetch>>)
      .mockResolvedValueOnce({
        body: new ReadableStream<Uint8Array>(),
        headers: new Headers({ location: 'https://another-provider.example.test/photo.jpg' }),
        status: 307,
      } as Awaited<ReturnType<typeof expoFetch>>);

    await expect(withAuthorizedDownloadStream(
      downloadAuthorizationPath,
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 0,
        rangeEndInclusive: 3,
        requestRange: false,
      },
      async () => undefined,
    )).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PHOTO_DELIVERY_REDIRECT_INVALID',
      status: 502,
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(2);
    expect(mockedExpoFetch.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      credentials: 'omit',
      redirect: 'error',
      headers: {
        Accept: 'image/jpeg,image/png,image/webp',
        'Cache-Control': 'no-store',
      },
    }));
  });

  it('does not treat a provider 403 as an app-session access denial', async () => {
    const accessDenied = jest.fn(async () => undefined);
    const unregister = registerAccessDeniedHandler(accessDenied);
    mockedExpoFetch
      .mockResolvedValueOnce({
        body: new ReadableStream<Uint8Array>(),
        headers: new Headers({
          location: 'https://objects.example.test/private/photo.jpg?opaque=expired',
          'x-gc-media-expires-at': new Date(Date.now() + 5 * 60_000).toISOString(),
        }),
        status: 307,
      } as Awaited<ReturnType<typeof expoFetch>>)
      .mockResolvedValueOnce({
        body: new ReadableStream<Uint8Array>(),
        headers: new Headers(),
        status: 403,
      } as Awaited<ReturnType<typeof expoFetch>>);

    try {
      await expect(withAuthorizedDownloadStream(
        downloadAuthorizationPath,
        'a'.repeat(32),
        {
          maximumBytes: 4,
          rangeStart: 0,
          rangeEndInclusive: 3,
          requestRange: false,
        },
        async () => undefined,
      )).rejects.toMatchObject<Partial<ApiError>>({
        code: 'PHOTO_DELIVERY_AUTH_EXPIRED',
        status: 503,
      });
      expect(accessDenied).not.toHaveBeenCalled();
    } finally {
      unregister();
    }
  });

  it('normalizes its internal timeout to a retryable API timeout', async () => {
    mockedExpoFetch.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      const signal = init?.signal;
      if (!signal) {
        reject(new Error('Expected a bounded request signal.'));
        return;
      }
      const rejectForAbort = () => reject(signal.reason);
      if (signal.aborted) rejectForAbort();
      else signal.addEventListener('abort', rejectForAbort, { once: true });
    }));

    await expect(withAuthorizedDownloadStream(
      downloadAuthorizationPath,
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 0,
        rangeEndInclusive: 3,
        requestRange: false,
        timeoutMs: 1,
      },
      async () => undefined,
    )).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PHOTO_DELIVERY_TIMEOUT',
      status: 408,
    });
  });

  it('normalizes a provider-hop timeout to the same retryable API timeout', async () => {
    mockedExpoFetch
      .mockResolvedValueOnce({
        body: new ReadableStream<Uint8Array>(),
        headers: new Headers({
          location: 'https://objects.example.test/private/photo.jpg?opaque=timeout',
          'x-gc-media-expires-at': new Date(Date.now() + 5 * 60_000).toISOString(),
        }),
        status: 307,
      } as Awaited<ReturnType<typeof expoFetch>>)
      .mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
        const signal = init?.signal;
        if (!signal) {
          reject(new Error('Expected a bounded provider request signal.'));
          return;
        }
        const rejectForAbort = () => reject(signal.reason);
        if (signal.aborted) rejectForAbort();
        else signal.addEventListener('abort', rejectForAbort, { once: true });
      }));

    await expect(withAuthorizedDownloadStream(
      downloadAuthorizationPath,
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 0,
        rangeEndInclusive: 3,
        requestRange: false,
        timeoutMs: 5,
      },
      async () => undefined,
    )).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PHOTO_DELIVERY_TIMEOUT',
      status: 408,
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(2);
  });

  it('normalizes a timeout raised by an in-flight response body read', async () => {
    let locked = false;
    const cancel = jest.fn(async () => undefined);
    mockedExpoFetch.mockImplementation(async (_url, init) => {
      const signal = init?.signal;
      if (!signal) throw new Error('Expected a bounded response-body signal.');
      const body = {
        get locked() {
          return locked;
        },
        cancel,
        getReader: () => {
          locked = true;
          return {
            read: () => new Promise<never>((_resolve, reject) => {
              const rejectForAbort = () => reject(signal.reason);
              if (signal.aborted) rejectForAbort();
              else signal.addEventListener('abort', rejectForAbort, { once: true });
            }),
            releaseLock: () => {
              locked = false;
            },
          };
        },
      } as unknown as ReadableStream<Uint8Array>;
      return {
        body,
        headers: new Headers({
          'content-length': '4',
          'content-type': 'image/jpeg',
        }),
        status: 200,
      } as Awaited<ReturnType<typeof expoFetch>>;
    });

    await expect(withAuthorizedDownloadStream(
      downloadAuthorizationPath,
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 0,
        rangeEndInclusive: 3,
        requestRange: false,
        timeoutMs: 1,
      },
      async (response) => {
        const reader = response.body.getReader();
        try {
          await reader.read();
        } finally {
          reader.releaseLock();
        }
      },
    )).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PHOTO_DELIVERY_TIMEOUT',
      status: 408,
    });
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it.each([
    'http://gc-photos.example.test/photo.jpg?signature=secret',
    sameOriginRedirect,
    'https://user:password@gc-photos.example.test/photo.jpg?signature=secret',
    'https://gc-photos.example.test/photo.jpg?signature=secret#fragment',
  ])('rejects an unsafe provider redirect without issuing a second request: %s', async (location) => {
    mockedExpoFetch.mockResolvedValue({
      body: new ReadableStream<Uint8Array>(),
      headers: new Headers({
        location,
        'x-gc-media-expires-at': new Date(Date.now() + 5 * 60_000).toISOString(),
      }),
      status: 307,
    } as Awaited<ReturnType<typeof expoFetch>>);

    await expect(withAuthorizedDownloadStream(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content',
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 0,
        rangeEndInclusive: 3,
        requestRange: false,
      },
      async () => undefined,
    )).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PHOTO_DELIVERY_REDIRECT_INVALID',
      status: 502,
    });
    expect(mockedExpoFetch).toHaveBeenCalledTimes(1);
  });

  it('fails closed when native response streaming is unavailable', async () => {
    mockedExpoFetch.mockResolvedValue({
      body: null,
      headers: new Headers(),
      status: 200,
    } as Awaited<ReturnType<typeof expoFetch>>);

    await expect(withAuthorizedDownloadStream(
      '/api/v1/mobile/trips/33333333-3333-4333-8333-333333333333/my-photos/download-authorizations/44444444-4444-4444-8444-444444444444/content',
      'a'.repeat(32),
      {
        maximumBytes: 4,
        rangeStart: 0,
        rangeEndInclusive: 3,
        requestRange: false,
      },
      async () => undefined,
    )).rejects.toMatchObject<Partial<ApiError>>({
      code: 'NATIVE_STREAM_UNAVAILABLE',
      status: 503,
    });
  });
});
