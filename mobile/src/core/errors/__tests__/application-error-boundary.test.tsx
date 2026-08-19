import { fireEvent, render, waitFor } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';
import { Text } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';

import { ApplicationErrorBoundary } from '../application-error-boundary';
import { clearApplicationDiagnosticsForTests, recentApplicationDiagnostics } from '../application-diagnostics';

const mockReloadAsync = jest.fn();
const mockRequestSafeSignOut = jest.fn();
const mockHideAsync = jest.fn(async () => undefined);
const mockCaptureApplicationRenderFailure = jest.fn();

jest.mock('expo-updates', () => ({ reloadAsync: (...args: unknown[]) => mockReloadAsync(...args) }));
jest.mock('expo-splash-screen', () => ({ hideAsync: () => mockHideAsync() }));
jest.mock('@/core/auth/use-safe-sign-out', () => ({
  requestSafeSignOut: (...args: unknown[]) => mockRequestSafeSignOut(...args),
}));
jest.mock('@/core/observability/mobile-observability', () => ({
  captureApplicationRenderFailure: (...args: unknown[]) =>
    mockCaptureApplicationRenderFailure(...args),
}));

function Crash({ enabled, children }: PropsWithChildren<{ enabled: boolean }>) {
  if (enabled) throw new Error('passport Z1234567 at C:\\private\\native.db');
  return <>{children}</>;
}

beforeEach(() => {
  clearApplicationDiagnosticsForTests();
  mockReloadAsync.mockReset();
  mockRequestSafeSignOut.mockReset();
  mockHideAsync.mockClear();
  mockCaptureApplicationRenderFailure.mockClear();
  useSessionStore.getState().clear();
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => jest.restoreAllMocks());

test('renders privacy-safe recovery copy and never exposes the thrown value', async () => {
  const view = await render(<ApplicationErrorBoundary><Crash enabled>secret</Crash></ApplicationErrorBoundary>);
  expect(view.getByText('Something interrupted the app.')).toBeTruthy();
  expect(view.queryByText(/passport|Z1234567|native\.db/i)).toBeNull();
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  expect(mockCaptureApplicationRenderFailure).toHaveBeenCalledWith(
    expect.any(Error),
    0,
  );
  expect(recentApplicationDiagnostics()).toEqual([{ code: 'APP_RENDER_FAILED', attempt: 0 }]);
});

test('remounts children for a bounded inline recovery', async () => {
  let shouldCrash = true;
  function Recoverable() {
    if (shouldCrash) throw new Error('sensitive native detail');
    return <Text>Recovered safely</Text>;
  }
  const view = await render(<ApplicationErrorBoundary><Recoverable /></ApplicationErrorBoundary>);
  shouldCrash = false;
  await fireEvent.press(view.getByRole('button', { name: 'Try again' }));
  expect(view.getByText('Recovered safely')).toBeTruthy();
});

test('stops offering inline recovery after two failed remounts', async () => {
  const view = await render(<ApplicationErrorBoundary><Crash enabled /></ApplicationErrorBoundary>);
  await fireEvent.press(view.getByRole('button', { name: 'Try again' }));
  await fireEvent.press(view.getByRole('button', { name: 'Try again' }));
  expect(view.queryByRole('button', { name: 'Try again' })).toBeNull();
  expect(view.getByRole('button', { name: 'Restart app' })).toBeTruthy();
});

test('offers the existing safe sign-out path only for an authenticated session', async () => {
  useSessionStore.setState({ status: 'authenticated', session: {} as never });
  mockRequestSafeSignOut.mockResolvedValue({ ok: true, namespace: null });
  const view = await render(<ApplicationErrorBoundary><Crash enabled /></ApplicationErrorBoundary>);
  await fireEvent.press(view.getByRole('button', { name: 'Sign out safely' }));
  expect(mockRequestSafeSignOut).toHaveBeenCalledTimes(1);
});

test('shows only generic copy when restart fails', async () => {
  mockReloadAsync.mockRejectedValue(new Error('provider token / private path'));
  const view = await render(<ApplicationErrorBoundary><Crash enabled /></ApplicationErrorBoundary>);
  await fireEvent.press(view.getByRole('button', { name: 'Restart app' }));
  await waitFor(() => expect(view.getByText('The app could not finish that recovery step. Restart and try again.')).toBeTruthy());
  expect(view.queryByText(/provider token|private path/i)).toBeNull();
});
