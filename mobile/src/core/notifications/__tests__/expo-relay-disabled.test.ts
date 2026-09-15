import { setAutoServerRegistrationEnabledAsync } from '../expo-relay-disabled';

const mockSetRegistrationInfo = jest.fn();
jest.mock('expo-modules-core', () => {
  const actual = jest.requireActual('expo-modules-core');
  return { ...actual,
    requireOptionalNativeModule: (name: string) => name === 'NotificationsServerRegistrationModule'
      ? { setRegistrationInfoAsync: (...args: unknown[]) => mockSetRegistrationInfo(...args) }
      : actual.requireOptionalNativeModule(name),
  };
});

beforeEach(() => { mockSetRegistrationInfo.mockReset().mockResolvedValue(undefined); });

test('retires only the legacy Expo relay preference', async () => {
  await setAutoServerRegistrationEnabledAsync(false);
  expect(mockSetRegistrationInfo).toHaveBeenCalledTimes(1);
  expect(mockSetRegistrationInfo).toHaveBeenCalledWith(null);
});

test('cannot enable the Expo relay through the compatibility export', async () => {
  await expect(setAutoServerRegistrationEnabledAsync(true)).rejects.toThrow('Expo push delivery is disabled');
  expect(mockSetRegistrationInfo).not.toHaveBeenCalled();
});
