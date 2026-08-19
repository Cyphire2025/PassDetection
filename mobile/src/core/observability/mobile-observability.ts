import * as Sentry from '@sentry/react-native';
import type {
  Event,
  ErrorEvent,
  Exception,
  Metric,
  ReactNativeOptions,
  StackFrame,
  Stacktrace,
  Thread,
} from '@sentry/react-native';

import { env } from '@/core/config/env';

const SAFE_ERROR_VALUE = 'redacted application failure';
const MAX_TEXT_LENGTH = 160;
const ALLOWED_TAGS = new Set(['diagnostic_code', 'recovery_attempt']);
const PROCESS_BOOTSTRAP_STARTED_AT_MS = performance.now();
const MOBILE_METRIC_SCHEMA = Object.freeze({
  bootstrap_duration: {
    name: 'gc.mobile.bootstrap_to_interactive.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 120_000,
  },
  sync_duration: {
    name: 'gc.mobile.sync.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 600_000,
  },
  background_sync_duration: {
    name: 'gc.mobile.background_sync.duration',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 300_000,
  },
  realtime_reconnect_delay: {
    name: 'gc.mobile.realtime.reconnect_delay',
    type: 'distribution',
    unit: 'millisecond',
    maximum: 120_000,
  },
  queue_depth: {
    name: 'gc.mobile.queue.depth',
    type: 'gauge',
    unit: 'item',
    maximum: 10_000,
  },
  sync_run: {
    name: 'gc.mobile.sync.run',
    type: 'counter',
    maximum: 1,
  },
  background_expiration: {
    name: 'gc.mobile.background.expiration',
    type: 'counter',
    maximum: 1,
  },
  realtime_reconnect: {
    name: 'gc.mobile.realtime.reconnect',
    type: 'counter',
    maximum: 1,
  },
} as const);
const METRIC_ATTRIBUTE_VALUES = Object.freeze({
  outcome: new Set(['success', 'partial', 'failure', 'cancelled', 'timeout', 'offline']),
  trigger: new Set(['startup', 'foreground', 'background', 'realtime', 'push', 'manual', 'mutation']),
  queue: new Set(['sync', 'attendance', 'documents']),
} satisfies Record<string, ReadonlySet<string>>);
const ALLOWED_CONTEXT_FIELDS = Object.freeze({
  app: new Set([
    'app_identifier',
    'app_memory',
    'app_name',
    'app_start_time',
    'app_version',
    'build_type',
    'free_memory',
    'in_foreground',
  ]),
  device: new Set([
    'arch',
    'battery_level',
    'battery_status',
    'brand',
    'charging',
    'cpu_description',
    'device_type',
    'family',
    'free_memory',
    'free_storage',
    'low_memory',
    'manufacturer',
    'memory_size',
    'model',
    'model_id',
    'online',
    'orientation',
    'processor_count',
    'processor_frequency',
    'screen_density',
    'screen_dpi',
    'screen_height_pixels',
    'screen_resolution',
    'screen_width_pixels',
    'simulator',
    'storage_size',
    'usable_memory',
  ]),
  os: new Set(['build', 'kernel_version', 'name', 'rooted', 'version']),
  runtime: new Set(['name', 'raw_description', 'version']),
} satisfies Record<string, ReadonlySet<string>>);

let initialized = false;

export type MobileMetricName = keyof typeof MOBILE_METRIC_SCHEMA;
export type MobileMetricAttributes = Readonly<{
  outcome?: 'success' | 'partial' | 'failure' | 'cancelled' | 'timeout' | 'offline';
  trigger?: 'startup' | 'foreground' | 'background' | 'realtime' | 'push' | 'manual' | 'mutation';
  queue?: 'sync' | 'attendance' | 'documents';
}>;

function boundedText(value: unknown, maximum = MAX_TEXT_LENGTH): string | undefined {
  if (typeof value !== 'string' || value.length === 0) return undefined;
  return value.slice(0, maximum);
}

function boundedNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function safeFrameFile(value: unknown): string | undefined {
  const text = boundedText(value, 512);
  if (!text) return undefined;
  const withoutParameters = text.split(/[?#]/, 1)[0]?.replace(/\\/g, '/');
  const basename = withoutParameters?.split('/').filter(Boolean).at(-1);
  if (!basename) return undefined;
  return `app:///${basename.slice(0, 180)}`;
}

function sanitizeStackFrame(frame: StackFrame): StackFrame {
  const filename = safeFrameFile(frame.filename ?? frame.abs_path);
  const functionName = boundedText(frame.function);
  const moduleName = boundedText(frame.module);
  const platform = boundedText(frame.platform, 40);
  const lineno = boundedNumber(frame.lineno);
  const colno = boundedNumber(frame.colno);
  const instructionAddress = boundedText(frame.instruction_addr, 80);
  const addressMode = boundedText(frame.addr_mode, 40);
  const debugId = boundedText(frame.debug_id, 80);
  return {
    ...(filename ? { filename } : {}),
    ...(functionName ? { function: functionName } : {}),
    ...(moduleName ? { module: moduleName } : {}),
    ...(platform ? { platform } : {}),
    ...(lineno !== undefined ? { lineno } : {}),
    ...(colno !== undefined ? { colno } : {}),
    ...(typeof frame.in_app === 'boolean' ? { in_app: frame.in_app } : {}),
    ...(instructionAddress ? { instruction_addr: instructionAddress } : {}),
    ...(addressMode ? { addr_mode: addressMode } : {}),
    ...(debugId ? { debug_id: debugId } : {}),
  };
}

function sanitizeStacktrace(stacktrace: Stacktrace | undefined): Stacktrace | undefined {
  if (!stacktrace) return undefined;
  const frames = stacktrace.frames?.slice(-150).map(sanitizeStackFrame);
  return {
    ...(frames ? { frames } : {}),
    ...(stacktrace.frames_omitted ? { frames_omitted: stacktrace.frames_omitted } : {}),
  };
}

function sanitizeException(exception: Exception): Exception {
  const mechanism = exception.mechanism;
  const moduleName = boundedText(exception.module);
  const stacktrace = sanitizeStacktrace(exception.stacktrace);
  const threadId =
    typeof exception.thread_id === 'number' || typeof exception.thread_id === 'string'
      ? exception.thread_id
      : undefined;
  const mechanismType = boundedText(mechanism?.type, 80) ?? 'generic';
  const exceptionId = boundedNumber(mechanism?.exception_id);
  const parentId = boundedNumber(mechanism?.parent_id);
  return {
    type: boundedText(exception.type, 100) ?? 'ApplicationFailure',
    value: SAFE_ERROR_VALUE,
    ...(moduleName ? { module: moduleName } : {}),
    ...(threadId !== undefined ? { thread_id: threadId } : {}),
    ...(stacktrace ? { stacktrace } : {}),
    ...(mechanism
      ? {
          mechanism: {
            type: mechanismType,
            ...(typeof mechanism.handled === 'boolean'
              ? { handled: mechanism.handled }
              : {}),
            ...(typeof mechanism.synthetic === 'boolean'
              ? { synthetic: mechanism.synthetic }
              : {}),
            ...(typeof mechanism.is_exception_group === 'boolean'
              ? { is_exception_group: mechanism.is_exception_group }
              : {}),
            ...(exceptionId !== undefined ? { exception_id: exceptionId } : {}),
            ...(parentId !== undefined ? { parent_id: parentId } : {}),
          },
        }
      : {}),
  };
}

function sanitizeThread(thread: Thread): Thread {
  const id =
    typeof thread.id === 'number' || typeof thread.id === 'string'
      ? thread.id
      : undefined;
  const stacktrace = sanitizeStacktrace(thread.stacktrace);
  return {
    ...(id !== undefined ? { id } : {}),
    ...(typeof thread.main === 'boolean' ? { main: thread.main } : {}),
    ...(typeof thread.crashed === 'boolean' ? { crashed: thread.crashed } : {}),
    ...(typeof thread.current === 'boolean' ? { current: thread.current } : {}),
    ...(stacktrace ? { stacktrace } : {}),
  };
}

function sanitizeContextValue(value: unknown): string | number | boolean | undefined {
  if (typeof value === 'boolean') return value;
  const numeric = boundedNumber(value);
  if (numeric !== undefined) return numeric;
  return boundedText(value);
}

function sanitizeContexts(event: Event): Event['contexts'] {
  const sanitized: NonNullable<Event['contexts']> = {};
  for (const [contextName, fields] of Object.entries(ALLOWED_CONTEXT_FIELDS)) {
    const source = event.contexts?.[contextName];
    if (!source) continue;
    const target: Record<string, string | number | boolean> = {};
    for (const field of fields) {
      const value = sanitizeContextValue(source[field]);
      if (value !== undefined) target[field] = value;
    }
    if (Object.keys(target).length > 0) sanitized[contextName] = target;
  }
  return Object.keys(sanitized).length > 0 ? sanitized : undefined;
}

function sanitizeDebugMeta(event: Event): Event['debug_meta'] {
  const images = event.debug_meta?.images?.slice(0, 100).map((image) => {
    if (image.type === 'macho') {
      const imageSize = boundedNumber(image.image_size);
      const codeFile = safeFrameFile(image.code_file);
      return {
        type: 'macho' as const,
        debug_id: boundedText(image.debug_id, 80) ?? 'unknown',
        image_addr: boundedText(image.image_addr, 80) ?? '0x0',
        ...(imageSize !== undefined ? { image_size: imageSize } : {}),
        ...(codeFile ? { code_file: codeFile } : {}),
      };
    }
    const codeId = image.type === 'wasm' ? boundedText(image.code_id, 80) : undefined;
    return {
      type: image.type,
      debug_id: boundedText(image.debug_id, 80) ?? 'unknown',
      code_file: safeFrameFile(image.code_file) ?? 'app:///bundle',
      ...(codeId ? { code_id: codeId } : {}),
    };
  });
  return images?.length ? { images } : undefined;
}

function sanitizeMetricAttributes(attributes: unknown): Record<string, string> | undefined {
  if (!attributes || typeof attributes !== 'object' || Array.isArray(attributes)) return undefined;
  const source = attributes as Record<string, unknown>;
  const safe: Record<string, string> = {};
  for (const [key, allowed] of Object.entries(METRIC_ATTRIBUTE_VALUES)) {
    const value = source[key];
    if (typeof value === 'string' && allowed.has(value)) safe[key] = value;
  }
  return Object.keys(safe).length > 0 ? safe : undefined;
}

/** Fail-closed projection for Sentry's separate metric envelope. */
export function sanitizeMobileObservabilityMetric(metric: Metric): Metric | null {
  const specification = Object.values(MOBILE_METRIC_SCHEMA).find(
    (candidate) => candidate.name === metric.name,
  );
  if (
    !specification
    || metric.type !== specification.type
    || !Number.isFinite(metric.value)
    || metric.value < 0
    || metric.value > specification.maximum
  ) {
    return null;
  }
  const attributes = sanitizeMetricAttributes(metric.attributes);
  return {
    name: specification.name,
    type: specification.type,
    value: metric.value,
    ...('unit' in specification ? { unit: specification.unit } : {}),
    ...(attributes ? { attributes } : {}),
  };
}

/**
 * Reduces every JavaScript event to a symbolication-safe allowlist. Native
 * crashes use the same no-PII, no-breadcrumb, no-attachment SDK settings, but
 * are serialized by the native SDK so they can survive a process crash.
 */
export function sanitizeMobileObservabilityEvent(event: Event): ErrorEvent {
  const tags = Object.fromEntries(
    Object.entries(event.tags ?? {})
      .filter(([key]) => ALLOWED_TAGS.has(key))
      .map(([key, value]) => [key, sanitizeContextValue(value)])
      .filter((entry): entry is [string, string | number | boolean] => entry[1] !== undefined),
  );

  const eventId = boundedText(event.event_id, 64);
  const timestamp = boundedNumber(event.timestamp);
  const platform = boundedText(event.platform, 40);
  const release = boundedText(event.release);
  const dist = boundedText(event.dist, 80);
  const environment = boundedText(event.environment, 40);
  const contexts = sanitizeContexts(event);
  const debugMeta = sanitizeDebugMeta(event);
  const sdkName = boundedText(event.sdk?.name, 100);
  const sdkVersion = boundedText(event.sdk?.version, 40);
  const sdkIntegrations = event.sdk?.integrations
    ?.slice(0, 50)
    .map((value) => value.slice(0, 80));
  const sdkPackages = event.sdk?.packages?.slice(0, 50).map((item) => ({
    name: item.name.slice(0, 100),
    version: item.version.slice(0, 40),
  }));
  const sdk = event.sdk
    ? {
        ...(sdkName ? { name: sdkName } : {}),
        ...(sdkVersion ? { version: sdkVersion } : {}),
        ...(sdkIntegrations ? { integrations: sdkIntegrations } : {}),
        ...(sdkPackages ? { packages: sdkPackages } : {}),
        settings: { infer_ip: 'never' as const },
      }
    : undefined;

  return {
    type: undefined,
    ...(eventId ? { event_id: eventId } : {}),
    ...(timestamp !== undefined ? { timestamp } : {}),
    ...(event.level ? { level: event.level } : {}),
    ...(platform ? { platform } : {}),
    ...(release ? { release } : {}),
    ...(dist ? { dist } : {}),
    ...(environment ? { environment } : {}),
    ...(event.exception?.values
      ? { exception: { values: event.exception.values.slice(-10).map(sanitizeException) } }
      : {}),
    ...(event.threads?.values
      ? { threads: { values: event.threads.values.slice(0, 100).map(sanitizeThread) } }
      : {}),
    ...(contexts ? { contexts } : {}),
    ...(Object.keys(tags).length > 0 ? { tags } : {}),
    ...(debugMeta ? { debug_meta: debugMeta } : {}),
    ...(sdk ? { sdk } : {}),
  };
}

export function createMobileObservabilityOptions(
  dsn: string,
  environment: 'development' | 'preview' | 'production',
): ReactNativeOptions {
  return {
    dsn,
    environment,
    enabled: true,
    debug: false,
    sendDefaultPii: false,
    sendClientReports: true,
    maxBreadcrumbs: 0,
    maxCacheItems: 20,
    maxQueueSize: 20,
    enableNative: true,
    autoInitializeNativeSdk: true,
    enableNativeCrashHandling: true,
    enableNdk: true,
    enableNdkScopeSync: false,
    enableWatchdogTerminationTracking: true,
    enableAppHangTracking: true,
    appHangTimeoutInterval: 2,
    enableAutoSessionTracking: true,
    attachThreads: false,
    attachScreenshot: false,
    attachViewHierarchy: false,
    enableCaptureFailedRequests: false,
    enableLogs: false,
    enableAutoPerformanceTracing: false,
    enableAppStartTracking: false,
    enableNativeFramesTracking: false,
    enableStallTracking: false,
    enableUserInteractionTracing: false,
    tracesSampleRate: 0,
    profilesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    tracePropagationTargets: [],
    beforeBreadcrumb: () => null,
    beforeSend: (event) => {
      try {
        return sanitizeMobileObservabilityEvent(event);
      } catch {
        return null;
      }
    },
    beforeSendTransaction: () => null,
    beforeSendMetric: sanitizeMobileObservabilityMetric,
  };
}

export function initializeMobileObservability(): void {
  if (initialized || !env.sentryDsn || env.demoModeRequested) return;
  Sentry.init(createMobileObservabilityOptions(env.sentryDsn, env.appEnv));
  initialized = true;
}

export function captureApplicationRenderFailure(error: unknown, attempt: number): void {
  if (!initialized) return;
  const reportableError = error instanceof Error ? error : new Error('APP_RENDER_FAILED');
  Sentry.captureException(reportableError, {
    level: 'error',
    tags: {
      diagnostic_code: 'APP_RENDER_FAILED',
      recovery_attempt: String(Math.max(0, Math.min(3, Math.trunc(attempt)))),
    },
  });
}

export function recordMobileMetric(
  name: MobileMetricName,
  value: number,
  attributes: MobileMetricAttributes = {},
): void {
  if (!initialized) return;
  const specification = MOBILE_METRIC_SCHEMA[name];
  const metric = sanitizeMobileObservabilityMetric({
    name: specification.name,
    type: specification.type,
    value,
    ...('unit' in specification ? { unit: specification.unit } : {}),
    attributes,
  });
  if (!metric) return;
  const options = {
    ...(metric.unit ? { unit: metric.unit } : {}),
    ...(metric.attributes ? { attributes: metric.attributes } : {}),
  };
  if (metric.type === 'distribution') {
    Sentry.metrics.distribution(metric.name, metric.value, options);
  } else if (metric.type === 'gauge') {
    Sentry.metrics.gauge(metric.name, metric.value, options);
  } else {
    Sentry.metrics.count(metric.name, metric.value, options);
  }
}

export function markApplicationInteractive(): void {
  if (!initialized) return;
  recordMobileMetric(
    'bootstrap_duration',
    Math.max(0, performance.now() - PROCESS_BOOTSTRAP_STARTED_AT_MS),
    { outcome: 'success', trigger: 'startup' },
  );
}
