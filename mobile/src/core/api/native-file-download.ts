import ReactNativeBlobUtil, {
  type FetchBlobResponse,
  type ReactNativeBlobUtilResponseInfo,
} from 'react-native-blob-util';

export type NativeFileDownloadResult = Readonly<{
  headers: Readonly<Record<string, string>>;
  redirects: readonly string[];
  status: number;
}>;

export class NativeFileDownloadTooLargeError extends Error {
  constructor() {
    super('The native download exceeded its allowed size.');
    this.name = 'NativeFileDownloadTooLargeError';
  }
}

function abortError(signal: AbortSignal): Error {
  if (signal.reason instanceof Error) return signal.reason;
  const error = new Error('The native download was cancelled.');
  error.name = 'AbortError';
  return error;
}

function normalizedHeaders(
  input: ReactNativeBlobUtilResponseInfo['headers'],
): Readonly<Record<string, string>> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return Object.freeze({});
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(input as Record<string, unknown>)) {
    if (typeof value === 'string') output[key.toLowerCase()] = value;
    else if (typeof value === 'number' && Number.isFinite(value)) {
      output[key.toLowerCase()] = String(value);
    }
  }
  return Object.freeze(output);
}

function validMaximumBytes(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0;
}

/**
 * Downloads directly through the platform networking stack into one exact
 * app-private path. Bytes never materialize as a full JavaScript ArrayBuffer.
 * Redirects are disabled so bearer and short-lived grant headers cannot be
 * forwarded to another origin.
 */
export async function downloadNativeFileBounded(options: Readonly<{
  destinationPath: string;
  headers: Readonly<Record<string, string>>;
  maximumBytes: number;
  signal: AbortSignal;
  timeoutMs: number;
  url: string;
}>): Promise<NativeFileDownloadResult> {
  if (!options.destinationPath.startsWith('/') || options.destinationPath.includes('\0')) {
    throw new Error('The native download destination was invalid.');
  }
  if (!validMaximumBytes(options.maximumBytes)) {
    throw new Error('The native download byte limit was invalid.');
  }
  if (!Number.isSafeInteger(options.timeoutMs) || options.timeoutMs < 1_000) {
    throw new Error('The native download timeout was invalid.');
  }
  if (options.signal.aborted) throw abortError(options.signal);

  let exceededLimit = false;
  let response: FetchBlobResponse | null = null;
  const request = ReactNativeBlobUtil.config({
    IOSBackgroundTask: false,
    fileCache: false,
    followRedirect: false,
    overwrite: true,
    path: options.destinationPath,
    timeout: options.timeoutMs,
    trusty: false,
  }).fetch('GET', options.url, { ...options.headers });
  void request.progress({ interval: 100 }, (received, total) => {
    if (
      received > options.maximumBytes
      || (total > 0 && total > options.maximumBytes)
    ) {
      exceededLimit = true;
      void request.cancel();
    }
  });
  const cancel = (): void => {
    void request.cancel();
  };
  options.signal.addEventListener('abort', cancel, { once: true });

  try {
    response = await request;
  } catch (error) {
    if (options.signal.aborted) throw abortError(options.signal);
    if (exceededLimit) throw new NativeFileDownloadTooLargeError();
    throw error;
  } finally {
    options.signal.removeEventListener('abort', cancel);
  }
  if (exceededLimit) throw new NativeFileDownloadTooLargeError();

  const info = response.info();
  if (!Number.isSafeInteger(info.status) || info.status < 100 || info.status > 599) {
    throw new Error('The native download returned an invalid status.');
  }
  return Object.freeze({
    headers: normalizedHeaders(info.headers),
    redirects: Object.freeze(Array.isArray(info.redirects) ? [...info.redirects] : []),
    status: info.status,
  });
}
