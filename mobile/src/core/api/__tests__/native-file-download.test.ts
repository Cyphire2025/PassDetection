import { Platform } from 'react-native';

import {
  downloadNativeFileBounded,
  NativeFileDownloadError,
  NativeFileDownloadTooLargeError,
  type NativeFileDownloadFailureKind,
} from '../native-file-download';

type NativeMock = {
  config: jest.Mock;
  fs: {
    dirs: { DocumentDir: string };
    mv: jest.Mock;
    unlink: jest.Mock;
  };
};

type MockResponse = Readonly<{
  headers?: unknown;
  infoError?: unknown;
  infoValue?: unknown;
  path?: string;
  pathError?: unknown;
  redirects?: unknown;
  status?: unknown;
}>;

type MockRequest = Promise<unknown> & {
  cancel: jest.Mock;
  progress: jest.Mock;
  taskId: unknown;
};

const ORIGINAL_PLATFORM = Platform.OS;
const DEFAULT_TASK_ID = '11111111-1111-4111-8111-111111111111';
const DEFAULT_NATIVE_PATH = nativePath(DEFAULT_TASK_ID);

function nativeModule(): NativeMock {
  return (jest.requireMock('react-native-blob-util') as { default: NativeMock }).default;
}

function nativePath(taskId: string): string {
  return `/private/files/ReactNativeBlobUtilTmp_${taskId}.gc_document_download_tmp`;
}

function requestResolving(info: MockResponse = {}, taskId: unknown = DEFAULT_TASK_ID): MockRequest {
  const response = {
    info: () => {
      if (info.infoError !== undefined) throw info.infoError;
      if (Object.hasOwn(info, 'infoValue')) return info.infoValue;
      return {
        headers: info.headers === undefined ? {} : info.headers,
        redirects: info.redirects === undefined ? [] : info.redirects,
        status: info.status === undefined ? 200 : info.status,
      };
    },
    path: () => {
      if (info.pathError !== undefined) throw info.pathError;
      return info.path ?? DEFAULT_NATIVE_PATH;
    },
  };
  const request = Promise.resolve(response) as MockRequest;
  request.taskId = taskId;
  request.cancel = jest.fn(() => request);
  request.progress = jest.fn(() => request);
  return request;
}

function requestRejecting(error: unknown, taskId: unknown = DEFAULT_TASK_ID): MockRequest {
  const request = Promise.reject(error) as MockRequest;
  request.taskId = taskId;
  request.cancel = jest.fn(() => request);
  request.progress = jest.fn(() => request);
  return request;
}

function installRequest(request: MockRequest): jest.Mock {
  const fetch = jest.fn(() => request);
  nativeModule().config.mockReturnValue({ fetch });
  return fetch;
}

function downloadOptions(
  overrides: Partial<Parameters<typeof downloadNativeFileBounded>[0]> = {},
): Parameters<typeof downloadNativeFileBounded>[0] {
  return {
    destinationPath: '/private/cache/download.tmp',
    headers: {},
    maximumBytes: 12,
    signal: new AbortController().signal,
    timeoutMs: 5_000,
    url: 'https://api.example.test/content',
    ...overrides,
  };
}

async function captureRejection(operation: Promise<unknown>): Promise<unknown> {
  try {
    await operation;
  } catch (error) {
    return error;
  }
  throw new Error('Expected the operation to reject.');
}

beforeEach(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  nativeModule().config = jest.fn();
  nativeModule().fs.dirs.DocumentDir = '/private/files';
  nativeModule().fs.mv.mockReset().mockResolvedValue(undefined);
  nativeModule().fs.unlink.mockReset().mockResolvedValue(undefined);
});

afterAll(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: ORIGINAL_PLATFORM });
});

test('uses an Android-owned cache file and moves it into the exact managed destination', async () => {
  const request = requestResolving({
    headers: { 'Content-Type': 'application/pdf', 'Content-Length': 12 },
    status: 206,
  });
  const fetch = installRequest(request);

  const result = await downloadNativeFileBounded(downloadOptions({
    headers: { Authorization: 'Bearer redacted' },
  }));

  expect(nativeModule().config).toHaveBeenCalledWith(expect.objectContaining({
    appendExt: 'gc_document_download_tmp',
    fileCache: true,
    followRedirect: false,
    overwrite: true,
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
  expect(Object.isFrozen(result)).toBe(true);
  expect(Object.isFrozen(result.headers)).toBe(true);
  expect(Object.isFrozen(result.redirects)).toBe(true);
  expect(nativeModule().fs.mv).toHaveBeenCalledWith(
    DEFAULT_NATIVE_PATH,
    '/private/cache/download.tmp',
  );
  expect(nativeModule().fs.unlink).not.toHaveBeenCalled();
});

test('normalizes safe bridge headers and copies valid redirect metadata', async () => {
  installRequest(requestResolving({
    headers: {
      Count: 7,
      Infinite: Number.POSITIVE_INFINITY,
      Missing: null,
      Type: 'image/png',
    },
    redirects: ['https://api.example.test/redirect-history'],
  }));

  const result = await downloadNativeFileBounded(downloadOptions());

  expect(result.headers).toEqual({ count: '7', type: 'image/png' });
  expect(result.redirects).toEqual(['https://api.example.test/redirect-history']);
});

test.each([
  ['relative destination', { destinationPath: 'private/cache/file' }, 'destination'],
  ['NUL in destination', { destinationPath: '/private/cache/\0file' }, 'destination'],
  ['zero byte ceiling', { maximumBytes: 0 }, 'byte limit'],
  ['fractional byte ceiling', { maximumBytes: 1.5 }, 'byte limit'],
  ['short timeout', { timeoutMs: 999 }, 'timeout'],
  ['fractional timeout', { timeoutMs: 1_000.5 }, 'timeout'],
] satisfies [
  string,
  Partial<Parameters<typeof downloadNativeFileBounded>[0]>,
  string,
][])(
  'rejects an invalid %s before starting native I/O',
  async (_name, overrides, message) => {
    await expect(downloadNativeFileBounded(downloadOptions(overrides))).rejects.toThrow(message);
    expect(nativeModule().config).not.toHaveBeenCalled();
  },
);

test('preserves an Error abort reason when already cancelled', async () => {
  const controller = new AbortController();
  const reason = new Error('account switched');
  controller.abort(reason);

  await expect(downloadNativeFileBounded(downloadOptions({ signal: controller.signal })))
    .rejects.toBe(reason);
  expect(nativeModule().config).not.toHaveBeenCalled();
});

test('creates a stable AbortError for a non-Error abort reason', async () => {
  const controller = new AbortController();
  controller.abort('signed out');

  const error = await captureRejection(
    downloadNativeFileBounded(downloadOptions({ signal: controller.signal })),
  );

  expect(error).toMatchObject({
    message: 'The native download was cancelled.',
    name: 'AbortError',
  });
});

test.each([
  ['received bytes', 13, -1],
  ['declared total', 1, 13],
])('cancels and removes the native temporary file when %s exceeds the ceiling', async (
  _name,
  received,
  total,
) => {
  const request = requestResolving();
  request.progress.mockImplementation((
    _config: unknown,
    listener: (current: number, expected: number) => void,
  ) => {
    listener(received, total);
    return request;
  });
  installRequest(request);

  await expect(downloadNativeFileBounded(downloadOptions()))
    .rejects.toBeInstanceOf(NativeFileDownloadTooLargeError);
  expect(request.cancel).toHaveBeenCalledTimes(1);
  expect(nativeModule().fs.mv).not.toHaveBeenCalled();
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test('accepts progress exactly at the byte ceiling', async () => {
  const request = requestResolving();
  request.progress.mockImplementation((
    _config: unknown,
    listener: (current: number, expected: number) => void,
  ) => {
    listener(12, 12);
    return request;
  });
  installRequest(request);

  await expect(downloadNativeFileBounded(downloadOptions())).resolves.toMatchObject({ status: 200 });
  expect(request.cancel).not.toHaveBeenCalled();
});

test('propagates caller cancellation and always removes its abort listener', async () => {
  let rejectRequest!: (error: unknown) => void;
  const request = new Promise((_resolve, reject) => {
    rejectRequest = reject;
  }) as MockRequest;
  request.taskId = DEFAULT_TASK_ID;
  request.cancel = jest.fn(() => {
    rejectRequest(new Error('native cancelled'));
    return request;
  });
  request.progress = jest.fn(() => request);
  installRequest(request);
  const controller = new AbortController();
  const removeListener = jest.spyOn(controller.signal, 'removeEventListener');
  const reason = new Error('account switched');

  const download = downloadNativeFileBounded(downloadOptions({ signal: controller.signal }));
  controller.abort(reason);

  await expect(download).rejects.toBe(reason);
  expect(request.cancel).toHaveBeenCalledTimes(1);
  expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function));
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test('honors cancellation even when the native request wins the settlement race', async () => {
  const request = requestResolving();
  installRequest(request);
  const controller = new AbortController();

  const download = downloadNativeFileBounded(downloadOptions({ signal: controller.signal }));
  controller.abort('signed out');

  await expect(download).rejects.toMatchObject({ name: 'AbortError' });
  expect(request.cancel).toHaveBeenCalledTimes(1);
  expect(nativeModule().fs.mv).not.toHaveBeenCalled();
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test.each([
  ['response_wrapper', new Error('Unexpected FileStorage response')],
  ['interrupted', 'Download interrupted by provider'],
  ['timeout', Object.assign(new Error('bridge timeout'), { code: 'ETIMEDOUT' })],
  ['local_storage', Object.assign(new Error('write failed'), { code: 'ENOSPC' })],
  ['network', Object.assign(new Error('transport failed'), { code: 'ECONNRESET' })],
  ['unknown', { opaque: true }],
] satisfies [NativeFileDownloadFailureKind, unknown][])(
  'classifies a rejected native request as %s without exposing its diagnostic',
  async (kind, cause) => {
    installRequest(requestRejecting(cause));

    const error = await captureRejection(downloadNativeFileBounded(downloadOptions()));

    expect(error).toBeInstanceOf(NativeFileDownloadError);
    expect(error).toMatchObject({
      cause,
      code: `NATIVE_FILE_DOWNLOAD_${kind.toUpperCase()}`,
      kind,
      message: 'The native file download failed.',
      name: 'NativeFileDownloadError',
    });
    expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
  },
);

test.each([
  ['missing task identity', null, '/private/files'],
  ['malformed task identity', '------------------------------------', '/private/files'],
  ['relative native directory', DEFAULT_TASK_ID, 'private/files'],
  ['traversing native directory', DEFAULT_TASK_ID, '/private/../files'],
] satisfies [string, unknown, string][])(
  'cancels fail-closed for %s',
  async (_name, taskId, documentDirectory) => {
    nativeModule().fs.dirs.DocumentDir = documentDirectory;
    const request = requestResolving({}, taskId);
    installRequest(request);

    await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
      code: 'NATIVE_FILE_DOWNLOAD_RESPONSE_WRAPPER',
      kind: 'response_wrapper',
    });
    expect(request.cancel).toHaveBeenCalledTimes(1);
    expect(nativeModule().fs.mv).not.toHaveBeenCalled();
  },
);

test('does not let a throwing cancellation bridge replace the metadata failure', async () => {
  const request = requestResolving({}, 'invalid');
  request.cancel.mockImplementation(() => {
    throw new Error('cancel bridge unavailable');
  });
  installRequest(request);

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'response_wrapper',
  });
});

test('classifies synchronous native configuration failures', async () => {
  nativeModule().config.mockImplementation(() => {
    throw Object.assign(new Error('cannot create file'), { code: 'EACCES' });
  });

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    code: 'NATIVE_FILE_DOWNLOAD_LOCAL_STORAGE',
    kind: 'local_storage',
  });
});

test('cleans up and classifies a synchronous progress-listener failure', async () => {
  const request = requestResolving();
  request.progress.mockImplementation(() => {
    throw new Error('socket event subscription failed');
  });
  installRequest(request);

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'network',
  });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test.each([null, [], 'invalid'])('rejects malformed response metadata: %p', async (infoValue) => {
  installRequest(requestResolving({ infoValue }));

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'response_wrapper',
  });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test.each([99, 600, 200.5, '200'])('rejects an invalid native status: %p', async (status) => {
  installRequest(requestResolving({ status }));

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    code: 'NATIVE_FILE_DOWNLOAD_RESPONSE_WRAPPER',
  });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test.each([null, 'https://api.example.test', [7]])(
  'rejects malformed native redirect metadata: %p',
  async (redirects) => {
    installRequest(requestResolving({ redirects }));

    await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
      kind: 'response_wrapper',
    });
  },
);

test('classifies an info-wrapper exception and removes the native file', async () => {
  installRequest(requestResolving({ infoError: new Error('Download interrupted') }));

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'interrupted',
  });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test('rejects an unexpected Android response path without deleting the untrusted path', async () => {
  installRequest(requestResolving({ path: '/untrusted/provider/file' }));

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'response_wrapper',
  });
  expect(nativeModule().fs.mv).not.toHaveBeenCalled();
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
  expect(nativeModule().fs.unlink).not.toHaveBeenCalledWith('/untrusted/provider/file');
});

test('classifies a native path exception and removes the expected temporary file', async () => {
  installRequest(requestResolving({ pathError: Object.assign(new Error('read path'), { code: 'EIO' }) }));

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'unknown',
  });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test('classifies a move failure and removes the remaining native temporary file', async () => {
  nativeModule().fs.mv.mockRejectedValue(Object.assign(new Error('read-only file system'), {
    code: 'EROFS',
  }));
  installRequest(requestResolving());

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    code: 'NATIVE_FILE_DOWNLOAD_LOCAL_STORAGE',
    kind: 'local_storage',
  });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test('does not let best-effort unlink failure replace the primary provider failure', async () => {
  const primary = new Error('Unexpected FileStorage response');
  nativeModule().fs.unlink.mockRejectedValue(new Error('unlink failed'));
  installRequest(requestRejecting(primary));

  const error = await captureRejection(downloadNativeFileBounded(downloadOptions()));

  expect(error).toMatchObject({ cause: primary, kind: 'response_wrapper' });
  expect(nativeModule().fs.unlink).toHaveBeenCalledWith(DEFAULT_NATIVE_PATH);
});

test('uses the direct exact-path strategy on the static iOS branch', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
  const request = requestResolving({ path: '/private/cache/download.tmp' });
  installRequest(request);

  await expect(downloadNativeFileBounded(downloadOptions())).resolves.toEqual({
    headers: {},
    redirects: [],
    status: 200,
  });
  expect(nativeModule().config).toHaveBeenCalledWith(expect.objectContaining({
    fileCache: false,
    path: '/private/cache/download.tmp',
  }));
  expect(nativeModule().fs.mv).not.toHaveBeenCalled();
  expect(nativeModule().fs.unlink).not.toHaveBeenCalled();
});

test('rejects an unexpected result path on the static iOS branch', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
  installRequest(requestResolving({ path: '/private/cache/other.tmp' }));

  await expect(downloadNativeFileBounded(downloadOptions())).rejects.toMatchObject({
    kind: 'response_wrapper',
  });
  expect(nativeModule().fs.mv).not.toHaveBeenCalled();
});
