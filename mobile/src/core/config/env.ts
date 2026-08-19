import { z } from 'zod';

const EnvSchema = z.object({
  apiUrl: z.string().url(),
  appEnv: z.enum(['development', 'preview', 'production']),
  easProjectId: z.string().uuid().optional(),
  realtimeEnabled: z.boolean(),
  appIntegrityMode: z.enum(['disabled', 'monitor', 'enforce']),
  playIntegrityCloudProjectNumber: z.string().regex(/^[1-9][0-9]{5,24}$/).optional(),
  sentryDsn: z.string().url().max(2_048).optional(),
});

const realtimeEnabled = z.enum(['true', 'false'])
  .parse(process.env.EXPO_PUBLIC_REALTIME_ENABLED ?? 'false') === 'true';

const parsed = EnvSchema.parse({
  apiUrl: process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000/api/v1',
  appEnv: process.env.EXPO_PUBLIC_APP_ENV ?? 'development',
  easProjectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID || undefined,
  realtimeEnabled,
  appIntegrityMode: process.env.EXPO_PUBLIC_APP_INTEGRITY_MODE ?? 'disabled',
  playIntegrityCloudProjectNumber:
    process.env.EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER || undefined,
  sentryDsn: process.env.EXPO_PUBLIC_SENTRY_DSN || undefined,
});

const demoModeRequested = process.env.EXPO_PUBLIC_DEMO_MODE === 'true';

if (demoModeRequested && parsed.appEnv !== 'development') {
  throw new Error('The local demo mode can only be bundled with the development app environment.');
}

const apiUrl = new URL(parsed.apiUrl);
const isLoopback = ['localhost', '127.0.0.1', '10.0.2.2'].includes(apiUrl.hostname);

if (parsed.appEnv !== 'development' && apiUrl.protocol !== 'https:') {
  throw new Error('Global Connect Travels requires an HTTPS API outside local development.');
}

if (apiUrl.protocol !== 'https:' && !isLoopback) {
  throw new Error('Cleartext API traffic is allowed only for a local development host.');
}

if (parsed.sentryDsn) {
  const sentryDsn = new URL(parsed.sentryDsn);
  if (
    sentryDsn.protocol !== 'https:' ||
    !sentryDsn.username ||
    sentryDsn.password ||
    sentryDsn.search ||
    sentryDsn.hash ||
    sentryDsn.pathname.split('/').filter(Boolean).length < 1
  ) {
    throw new Error('The crash-reporting DSN is not a valid public HTTPS Sentry DSN.');
  }
}

if (parsed.appEnv === 'production' && !parsed.sentryDsn) {
  throw new Error('Production builds require privacy-safe crash and ANR reporting.');
}

if (parsed.appIntegrityMode !== 'disabled' && !parsed.playIntegrityCloudProjectNumber) {
  throw new Error(
    'Enabled app integrity requires the public Google Cloud project number for Android.',
  );
}

export const env = Object.freeze({
  apiUrl: parsed.apiUrl.replace(/\/$/, ''),
  appEnv: parsed.appEnv,
  isDevelopment: parsed.appEnv === 'development',
  easProjectId: parsed.easProjectId,
  realtimeEnabled: parsed.realtimeEnabled,
  appIntegrityMode: parsed.appIntegrityMode,
  playIntegrityCloudProjectNumber: parsed.playIntegrityCloudProjectNumber,
  sentryDsn: parsed.sentryDsn,
  demoModeRequested,
});
