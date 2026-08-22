import ReactNativeBlobUtil, {
  type FetchBlobResponse,
  type ReactNativeBlobUtilResponseInfo,
  type StatefulPromise,
} from 'react-native-blob-util';
import { Platform } from 'react-native';

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

export type NativeFileDownloadFailureKind =
  | 'interrupted'
  | 'local_storage'
  | 'network'
  | 'response_wrapper'
  | 'timeout'
  | 'unknown';

/**
 * Keeps native/provider diagnostics out of UI and telemetry while retaining a
 * stable, low-cardinality reason that support and retry policy can act on.
 */
export class NativeFileDownloadError extends Error {
  readonly code: string;
  readonly kind: NativeFileDownloadFailureKind;

  constructor(kind: NativeFileDownloadFailureKind, cause: unknown) {
    super('The native file download failed.', { cause });
    this.name = 'NativeFileDownloadError';
    this.kind = kind;
    this.code = `NATIVE_FILE_DOWNLOAD_${kind.toUpperCase()}`;
  }
}

const ANDROID_NATIVE_CACHE_SUFFIX = 'gc_document_download_tmp';

function nativeFailureText(error: unknown): string {
  if (error instanceof Error) {
    const code = 'code' in error && typeof error.code === 'string' ? error.code : '';
    return `${code} ${error.message}`.trim();
  }
  return typeof error === 'string' ? error : '';
}

function nativeFailureKind(error: unknown): NativeFileDownloadFailureKind {
  const diagnostic = nativeFailureText(error);
  if (/unexpected filestorage response/i.test(diagnostic)) return 'response_wrapper';
  if (/download interrupted|cancel(?:led|ed)/i.test(diagnostic)) return 'interrupted';
  if (/timed?\s*out|timeout/i.test(diagnostic)) return 'timeout';
  if (/\be(?:acces|exist|isdir|noent|nospc|notdir|perm|rofs)\b|permission|create (?:dir|directory|file)|output path|no space|storage/i.test(diagnostic)) {
    return 'local_storage';
  }
  if (/\be(?:ai_again|connaborted|connrefused|connreset|hostunreach|netdown|netunreach)\b|network|connection|socket|host|dns|ssl|request error|unexpected end of stream/i.test(diagnostic)) {
    return 'network';
  }
  return 'unknown';
}

async function removeNativeTemporaryFile(path: string | null): Promise<void> {
  if (!path) return;
  await ReactNativeBlobUtil.fs.unlink(path).catch(() => undefined);
}

function cancelNativeRequest(request: StatefulPromise<FetchBlobResponse>): void {
  try {
    // Native implementations return the same stateful promise from cancel().
    // Consume its rejection so cancellation cannot become an unhandled promise.
    void Promise.resolve(request.cancel()).catch(() => undefined);
  } catch {
    // Cancellation is best effort. The original abort/limit/provider failure is
    // the actionable result and must not be replaced by a bridge exception.
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
  let androidTemporaryPath: string | null = null;
  let response: FetchBlobResponse | null = null;
  const nativeOptions = Platform.OS === 'android'
    ? {
        appendExt: ANDROID_NATIVE_CACHE_SUFFIX,
        fileCache: true,
      }
    : {
        fileCache: false,
        path: options.destinationPath,
      };
  let request: StatefulPromise<FetchBlobResponse>;
  try {
    request = ReactNativeBlobUtil.config({
      IOSBackgroundTask: false,
      followRedirect: false,
      overwrite: true,
      timeout: options.timeoutMs,
      trusty: false,
      ...nativeOptions,
    }).fetch('GET', options.url, { ...options.headers });
  } catch (error) {
    throw new NativeFileDownloadError(nativeFailureKind(error), error);
  }
  let abortListenerRegistered = false;
  let requestSettled = false;
  const cancel = (): void => {
    cancelNativeRequest(request);
  };

  try {
    if (Platform.OS === 'android') {
      const taskId = (request as typeof request & { taskId?: unknown }).taskId;
      const rawDocumentDirectory: unknown = ReactNativeBlobUtil.fs.dirs.DocumentDir;
      const documentDirectory = typeof rawDocumentDirectory === 'string'
        ? rawDocumentDirectory.replace(/\/+$/, '')
        : '';
      if (
        typeof taskId !== 'string'
        || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(taskId)
        || !documentDirectory.startsWith('/')
        || documentDirectory.startsWith('//')
        || /[\u0000-\u001f\u007f]/.test(documentDirectory)
        || /\/(?:\.{1,2})(?:\/|$)/.test(documentDirectory)
      ) {
        throw new NativeFileDownloadError(
          'response_wrapper',
          new Error('The native download returned invalid task metadata.'),
        );
      }
      androidTemporaryPath = `${documentDirectory}/ReactNativeBlobUtilTmp_${taskId}.${ANDROID_NATIVE_CACHE_SUFFIX}`;
    }
    void request.progress({ interval: 100 }, (received, total) => {
      if (
        received > options.maximumBytes
        || (total > 0 && total > options.maximumBytes)
      ) {
        exceededLimit = true;
        cancelNativeRequest(request);
      }
    });
    options.signal.addEventListener('abort', cancel, { once: true });
    abortListenerRegistered = true;

    try {
      response = await request;
      requestSettled = true;
    } catch (error) {
      requestSettled = true;
      if (options.signal.aborted) throw abortError(options.signal);
      if (exceededLimit) throw new NativeFileDownloadTooLargeError();
      throw new NativeFileDownloadError(nativeFailureKind(error), error);
    }

    if (options.signal.aborted) throw abortError(options.signal);
    if (exceededLimit) throw new NativeFileDownloadTooLargeError();

    try {
      const rawInfo: unknown = response.info();
      if (!rawInfo || typeof rawInfo !== 'object' || Array.isArray(rawInfo)) {
        throw new NativeFileDownloadError(
          'response_wrapper',
          new Error('The native download returned invalid response metadata.'),
        );
      }
      const info = rawInfo as ReactNativeBlobUtilResponseInfo;
      if (!Number.isSafeInteger(info.status) || info.status < 100 || info.status > 599) {
        throw new NativeFileDownloadError(
          'response_wrapper',
          new Error('The native download returned an invalid status.'),
        );
      }
      if (
        !Array.isArray(info.redirects)
        || info.redirects.some((redirect) => typeof redirect !== 'string')
      ) {
        throw new NativeFileDownloadError(
          'response_wrapper',
          new Error('The native download returned invalid redirect metadata.'),
        );
      }
      const responsePath = response.path();
      if (Platform.OS === 'android') {
        if (!androidTemporaryPath || responsePath !== androidTemporaryPath) {
          throw new NativeFileDownloadError(
            'response_wrapper',
            new Error('The native download returned an unexpected managed path.'),
          );
        }
        await ReactNativeBlobUtil.fs.mv(responsePath, options.destinationPath);
        androidTemporaryPath = null;
      } else if (responsePath !== options.destinationPath) {
        throw new NativeFileDownloadError(
          'response_wrapper',
          new Error('The native download returned an unexpected destination path.'),
        );
      }
      return Object.freeze({
        headers: normalizedHeaders(info.headers),
        redirects: Object.freeze([...info.redirects]),
        status: info.status,
      });
    } catch (error) {
      if (error instanceof NativeFileDownloadError) throw error;
      throw new NativeFileDownloadError(nativeFailureKind(error), error);
    }
  } catch (error) {
    if (!requestSettled) cancelNativeRequest(request);
    if (
      error instanceof NativeFileDownloadError
      || error instanceof NativeFileDownloadTooLargeError
    ) {
      throw error;
    }
    if (options.signal.aborted) throw abortError(options.signal);
    throw new NativeFileDownloadError(nativeFailureKind(error), error);
  } finally {
    if (abortListenerRegistered) options.signal.removeEventListener('abort', cancel);
    await removeNativeTemporaryFile(androidTemporaryPath);
  }
}
