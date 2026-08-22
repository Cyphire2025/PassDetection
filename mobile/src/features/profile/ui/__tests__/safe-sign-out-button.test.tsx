import { fireEvent, render } from '@testing-library/react-native';
import { Alert } from 'react-native';

import { SafeSignOutButton } from '../safe-sign-out-button';

const mockDiscardAndSignOut = jest.fn(async () => undefined);
const mockSynchronizeAndSignOut = jest.fn(async () => undefined);

jest.mock('@/core/auth/use-safe-sign-out', () => ({
  useSafeSignOut: () => ({
    blockedActions: {
      pending: 2,
      sending: 0,
      retryable: 1,
      unresolvedReview: 0,
      unsynchronized: 3,
      unsynchronizedAttendanceScans: 3,
      unsynchronizedOtherActions: 0,
    },
    discardAndSignOut: mockDiscardAndSignOut,
    errorMessage: '3 scans have not reached the server.',
    isSigningOut: false,
    retryCleanup: jest.fn(),
    signOut: jest.fn(),
    synchronizeAndSignOut: mockSynchronizeAndSignOut,
  }),
}));

beforeEach(() => {
  mockDiscardAndSignOut.mockClear();
  mockSynchronizeAndSignOut.mockClear();
  jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('keeps synchronization as the default recovery action', async () => {
  const screen = await render(<SafeSignOutButton testID="staff-sign-out" />);

  await fireEvent.press(screen.getByTestId('staff-sign-out-synchronize'));

  expect(mockSynchronizeAndSignOut).toHaveBeenCalledTimes(1);
  expect(mockDiscardAndSignOut).not.toHaveBeenCalled();
});

test('requires a second destructive confirmation before discarding local changes', async () => {
  const screen = await render(<SafeSignOutButton testID="staff-sign-out" />);

  await fireEvent.press(screen.getByTestId('staff-sign-out-discard'));

  expect(mockDiscardAndSignOut).not.toHaveBeenCalled();
  expect(Alert.alert).toHaveBeenCalledWith(
    'Discard unsynchronized changes?',
    expect.stringContaining('cannot be undone'),
    expect.arrayContaining([
      expect.objectContaining({ text: 'Keep me signed in', style: 'cancel' }),
      expect.objectContaining({ text: 'Discard and sign out', style: 'destructive' }),
    ]),
  );

  const actions = jest.mocked(Alert.alert).mock.calls[0]?.[2];
  const destructive = actions?.find((action) => action.style === 'destructive');
  destructive?.onPress?.();
  expect(mockDiscardAndSignOut).toHaveBeenCalledTimes(1);
});
