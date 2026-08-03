jest.mock('expo-secure-store', () => ({
  AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 3,
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
