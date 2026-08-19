import {
  downloadNativeFileBounded,
  NativeFileDownloadTooLargeError,
} from '../native-file-download';

type NativeMock = {
  config: jest.Mock;
};

function nativeModule(): NativeMock {
  return (jest.requireMock('react-native-blob-util') as { default: NativeMock }).default;
}

function requestResolving(info: Readonly<{
  headers?: Record<string, string | number>;
  redirects?: string[];
  status?: number;
}> = {}) {
  const response = {
    info: () => ({
      headers: info.headers ?? {},
      redirects: info.redirects ?? [],
      status: info.status ?? 200,
    }),
  };
  const request = Promise.resolve(response) as Promise<typeof response> & {
    cancel: jest.Mock;
    progress: jest.Mock;
  };
  request.cancel = jest.fn(() => request);
  request.progress = jest.fn(() => request);
  return request;
}

beforeEach(() => {
  nativeModule().config = jest.fn();
});

test('uses a fixed native path, disables redirects, and normalizes response headers', async () => {
  const request = requestResolving({
    headers: { 'Content-Type': 'application/pdf', 'Content-Length': 12 },
    status: 206,
  });
  const fetch = jest.fn(() => request);
  nativeModule().config.mockReturnValue({ fetch });

  const result = await downloadNativeFileBounded({
    destinationPath: '/private/cache/download.tmp',
    headers: { Authorization: 'Bearer redacted' },
    maximumBytes: 12,
    signal: new AbortController().signal,
    timeoutMs: 5_000,
    url: 'https://api.example.test/content',
  });

  expect(nativeModule().config).toHaveBeenCalledWith(expect.objectContaining({
    fileCache: false,
    followRedirect: false,
    overwrite: true,
    path: '/private/cache/download.tmp',
    trusty: false,
  }));
  expect(fetch).toHaveBeenCalledWith(
    'GET',
    'https://api.example.test/content',
    { Authorization: 'Bearer redacted' },
  );
  expect(result).toEqual({
    headers: { 'content-type': 'application/pdf', 'content-length': '12' },
    redirects: [],
    status: 206,
  });
});

test('cancels before completion when native progress exceeds the byte ceiling', async () => {
  let rejectRequest!: (error: unknown) => void;
  const request = new Promise((_resolve, reject) => {
    rejectRequest = reject;
  }) as Promise<never> & { cancel: jest.Mock; progress: jest.Mock };
  request.cancel = jest.fn(() => {
    rejectRequest(new Error('cancelled'));
    return request;
  });
  request.progress = jest.fn((_config, listener: (received: number, total: number) => void) => {
    listener(13, -1);
    return request;
  });
  nativeModule().config.mockReturnValue({ fetch: jest.fn(() => request) });

  await expect(downloadNativeFileBounded({
    destinationPath: '/private/cache/download.tmp',
    headers: {},
    maximumBytes: 12,
    signal: new AbortController().signal,
    timeoutMs: 5_000,
    url: 'https://api.example.test/content',
  })).rejects.toBeInstanceOf(NativeFileDownloadTooLargeError);
  expect(request.cancel).toHaveBeenCalledTimes(1);
});

test('propagates caller cancellation and removes its abort listener', async () => {
  let rejectRequest!: (error: unknown) => void;
  const request = new Promise((_resolve, reject) => {
    rejectRequest = reject;
  }) as Promise<never> & { cancel: jest.Mock; progress: jest.Mock };
  request.cancel = jest.fn(() => {
    rejectRequest(new Error('cancelled'));
    return request;
  });
  request.progress = jest.fn(() => request);
  nativeModule().config.mockReturnValue({ fetch: jest.fn(() => request) });
  const controller = new AbortController();

  const download = downloadNativeFileBounded({
    destinationPath: '/private/cache/download.tmp',
    headers: {},
    maximumBytes: 12,
    signal: controller.signal,
    timeoutMs: 5_000,
    url: 'https://api.example.test/content',
  });
  controller.abort(new Error('account switched'));

  await expect(download).rejects.toThrow('account switched');
  expect(request.cancel).toHaveBeenCalledTimes(1);
});
