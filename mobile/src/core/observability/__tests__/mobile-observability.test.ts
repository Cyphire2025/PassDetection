import type { Event } from '@sentry/react-native';

import {
  createMobileObservabilityOptions,
  sanitizeMobileObservabilityEvent,
  sanitizeMobileObservabilityMetric,
} from '../mobile-observability';

const secret = 'passport-Z1234567-account-991';

test('removes identity, request, breadcrumb, arbitrary context, and error-message data', () => {
  const event: Event = {
    event_id: '0123456789abcdef',
    message: secret,
    transaction: `/passenger/${secret}`,
    request: {
      url: `https://api.example.test/document/${secret}`,
      headers: { authorization: `Bearer ${secret}` },
    },
    user: { id: secret, email: `${secret}@example.test` },
    breadcrumbs: [{ message: secret, data: { token: secret } }],
    extra: { sql: secret },
    tags: { diagnostic_code: 'APP_RENDER_FAILED', passenger: secret },
    contexts: {
      device: {
        name: secret,
        device_unique_identifier: secret,
        model: 'Pixel 9',
        low_memory: true,
      },
      app: { app_identifier: 'com.globalconnects.groupcompanion' },
      response: { headers: { authorization: secret } },
    },
    exception: {
      values: [
        {
          type: 'DatabaseError',
          value: secret,
          mechanism: { type: 'generic', handled: false, data: { sql: secret } },
          stacktrace: {
            frames: [
              {
                filename: `C:\\Users\\${secret}\\index.android.bundle?token=${secret}`,
                function: 'loadPassengerDocument',
                lineno: 42,
                context_line: secret,
                vars: { passenger: secret },
              },
            ],
          },
        },
      ],
    },
  };

  const sanitized = sanitizeMobileObservabilityEvent(event);
  const serialized = JSON.stringify(sanitized);

  expect(serialized).not.toContain(secret);
  expect(sanitized.message).toBeUndefined();
  expect(sanitized.user).toBeUndefined();
  expect(sanitized.request).toBeUndefined();
  expect(sanitized.breadcrumbs).toBeUndefined();
  expect(sanitized.exception?.values?.[0]).toMatchObject({
    type: 'DatabaseError',
    value: 'redacted application failure',
    stacktrace: {
      frames: [
        {
          filename: 'app:///index.android.bundle',
          function: 'loadPassengerDocument',
          lineno: 42,
        },
      ],
    },
  });
  expect(sanitized.contexts?.device).toEqual({ model: 'Pixel 9', low_memory: true });
  expect(sanitized.tags).toEqual({ diagnostic_code: 'APP_RENDER_FAILED' });
});

test('keeps debug identifiers needed for symbolication but removes native paths', () => {
  const event: Event = {
    debug_meta: {
      images: [
        {
          type: 'sourcemap',
          debug_id: 'c6408e8a-5b01-4caf-a2f3-62c0442378c3',
          code_file: `/private/${secret}/index.ios.bundle`,
        },
        {
          type: 'macho',
          debug_id: '32848db7-78ea-402b-9731-508e04c1c665',
          image_addr: '0x1000',
          image_size: 4096,
          code_file: `/private/${secret}/GroupCompanion`,
        },
      ],
    },
  };

  const sanitized = sanitizeMobileObservabilityEvent(event);
  expect(JSON.stringify(sanitized)).not.toContain(secret);
  expect(sanitized.debug_meta?.images).toEqual([
    {
      type: 'sourcemap',
      debug_id: 'c6408e8a-5b01-4caf-a2f3-62c0442378c3',
      code_file: 'app:///index.ios.bundle',
    },
    {
      type: 'macho',
      debug_id: '32848db7-78ea-402b-9731-508e04c1c665',
      image_addr: '0x1000',
      image_size: 4096,
      code_file: 'app:///GroupCompanion',
    },
  ]);
});

test('configures native crash and hang evidence without content capture or tracing', () => {
  const options = createMobileObservabilityOptions(
    'https://public-key@o0.ingest.sentry.io/12345',
    'production',
  );

  expect(options).toMatchObject({
    sendDefaultPii: false,
    maxBreadcrumbs: 0,
    enableNativeCrashHandling: true,
    enableNdk: true,
    enableAppHangTracking: true,
    enableWatchdogTerminationTracking: true,
    attachScreenshot: false,
    attachViewHierarchy: false,
    enableCaptureFailedRequests: false,
    enableLogs: false,
    enableAutoPerformanceTracing: false,
    tracesSampleRate: 0,
    profilesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    tracePropagationTargets: [],
  });
  expect(options.beforeBreadcrumb?.({ message: secret }, {})).toBeNull();
});

test('allows only fixed low-cardinality SLO metrics and attributes', () => {
  expect(sanitizeMobileObservabilityMetric({
    name: 'gc.mobile.sync.duration',
    type: 'distribution',
    value: 1_250,
    unit: 'custom-unit-is-ignored',
    attributes: {
      outcome: 'success',
      trigger: 'realtime',
      passenger_id: secret,
      arbitrary: secret,
    },
  })).toEqual({
    name: 'gc.mobile.sync.duration',
    type: 'distribution',
    value: 1_250,
    unit: 'millisecond',
    attributes: { outcome: 'success', trigger: 'realtime' },
  });

  expect(sanitizeMobileObservabilityMetric({
    name: `gc.mobile.${secret}`,
    type: 'gauge',
    value: 1,
    attributes: { outcome: 'success' },
  })).toBeNull();
  expect(sanitizeMobileObservabilityMetric({
    name: 'gc.mobile.queue.depth',
    type: 'gauge',
    value: 10_001,
  })).toBeNull();
  expect(sanitizeMobileObservabilityMetric({
    name: 'gc.mobile.sync.run',
    type: 'counter',
    value: 1,
    attributes: { outcome: secret },
  })).toEqual({
    name: 'gc.mobile.sync.run',
    type: 'counter',
    value: 1,
  });
});
