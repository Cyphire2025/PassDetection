jest.mock('expo-secure-store', () => ({
  AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 3,
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 6,
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));

jest.mock('react-native-blob-util', () => ({
  __esModule: true,
  default: {
    ios: {
      excludeFromBackupKey: jest.fn(async () => undefined),
    },
  },
}));

// Native crash transports and offline flush timers do not belong in unit
// tests. Contract tests exercise our options/scrubbers against this inert SDK
// boundary; signed release builds own native crash/ANR integration proof.
jest.mock('@sentry/react-native', () => ({
  appLoaded: jest.fn(),
  captureException: jest.fn(),
  init: jest.fn(),
  metrics: {
    count: jest.fn(),
    distribution: jest.fn(),
    gauge: jest.fn(),
  },
}));
