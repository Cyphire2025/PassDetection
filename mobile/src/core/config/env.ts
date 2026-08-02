import { z } from 'zod';

const EnvSchema = z.object({
  apiUrl: z.string().url(),
  appEnv: z.enum(['development', 'preview', 'production']),
  easProjectId: z.string().uuid().optional(),
});

const parsed = EnvSchema.parse({
  apiUrl: process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000/api/v1',
  appEnv: process.env.EXPO_PUBLIC_APP_ENV ?? 'development',
  easProjectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID || undefined,
});

const demoModeRequested = process.env.EXPO_PUBLIC_DEMO_MODE === 'true';

if (demoModeRequested && parsed.appEnv !== 'development') {
  throw new Error('The local demo mode can only be bundled with the development app environment.');
}

const apiUrl = new URL(parsed.apiUrl);
const isLoopback = ['localhost', '127.0.0.1', '10.0.2.2'].includes(apiUrl.hostname);

if (parsed.appEnv !== 'development' && apiUrl.protocol !== 'https:') {
  throw new Error('Group Companion requires an HTTPS API outside local development.');
}

if (apiUrl.protocol !== 'https:' && !isLoopback) {
  throw new Error('Cleartext API traffic is allowed only for a local development host.');
}

export const env = Object.freeze({
  apiUrl: parsed.apiUrl.replace(/\/$/, ''),
  appEnv: parsed.appEnv,
  isDevelopment: parsed.appEnv === 'development',
  easProjectId: parsed.easProjectId,
  demoModeRequested,
});
