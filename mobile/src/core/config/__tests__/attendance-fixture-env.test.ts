/* eslint-disable @typescript-eslint/no-require-imports -- isolated module loads exercise static Expo env parsing. */

const MANAGED_KEYS = [
  'EXPO_PUBLIC_API_URL',
  'EXPO_PUBLIC_APP_ENV',
  'EXPO_PUBLIC_APP_INTEGRITY_MODE',
  'EXPO_PUBLIC_DEMO_MODE',
  'EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE',
  'EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER',
  'EXPO_PUBLIC_REALTIME_ENABLED',
  'EXPO_PUBLIC_SENTRY_DSN',
] as const;

const originalValues = Object.fromEntries(
  MANAGED_KEYS.map((key) => [key, process.env[key]]),
);

function loadEnvironment() {
  let loaded!: typeof import('../env').env;
  jest.isolateModules(() => {
    loaded = (require('../env') as typeof import('../env')).env;
  });
  return loaded;
}

beforeEach(() => {
  jest.resetModules();
  for (const key of MANAGED_KEYS) delete process.env[key];
  process.env.EXPO_PUBLIC_API_URL = 'https://preview.example.test/api/v1';
  process.env.EXPO_PUBLIC_APP_ENV = 'preview';
  process.env.EXPO_PUBLIC_APP_INTEGRITY_MODE = 'disabled';
  process.env.EXPO_PUBLIC_DEMO_MODE = 'false';
  process.env.EXPO_PUBLIC_REALTIME_ENABLED = 'false';
});

afterAll(() => {
  for (const key of MANAGED_KEYS) {
    const value = originalValues[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

test('enables the synthetic attendance seam only in an explicit preview artifact', () => {
  process.env.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE = 'true';
  expect(loadEnvironment().maestroAttendanceFixtureEnabled).toBe(true);
});

test('keeps ordinary preview artifacts fixture-free by default', () => {
  expect(loadEnvironment().maestroAttendanceFixtureEnabled).toBe(false);
});

test('rejects fixture activation in a development or production app environment', () => {
  process.env.EXPO_PUBLIC_APP_ENV = 'development';
  process.env.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE = 'true';
  expect(() => loadEnvironment()).toThrow(
    'The synthetic attendance fixture can only be bundled with the preview app environment.',
  );
});

test('rejects malformed fixture flags instead of treating them as disabled', () => {
  process.env.EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE = 'yes';
  expect(() => loadEnvironment()).toThrow();
});
