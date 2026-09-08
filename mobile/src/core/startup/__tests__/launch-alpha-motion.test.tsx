/* eslint-disable @typescript-eslint/no-require-imports -- Expo image uses a ref-driven native animation API. */
import { act, fireEvent, render } from '@testing-library/react-native';

import { LaunchAlphaMotion } from '../launch-alpha-motion';

const mockStartAnimating = jest.fn(async () => undefined);
const mockStopAnimating = jest.fn(async () => undefined);

jest.mock('expo-image', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    Image: React.forwardRef(function MockImage(props: Record<string, unknown>, ref) {
      React.useImperativeHandle(ref, () => ({ startAnimating: mockStartAnimating, stopAnimating: mockStopAnimating }));
      return React.createElement(MockView, props);
    }),
  };
});

async function advance(milliseconds: number) {
  await act(async () => { jest.advanceTimersByTime(milliseconds); });
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockStartAnimating.mockResolvedValue(undefined);
  mockStopAnimating.mockResolvedValue(undefined);
});

afterEach(() => { jest.useRealTimers(); });

test('starts the transparent animation only when loaded and foregrounded, and preserves five seconds through a pause', async () => {
  const complete = jest.fn();
  const screen = await render(<LaunchAlphaMotion playing={false} onComplete={complete} />);
  expect(screen.getByTestId('launch-alpha-motion').props).toMatchObject({ autoplay: false, contentFit: 'contain', transition: 0 });
  await fireEvent(screen.getByTestId('launch-alpha-motion'), 'load');
  await advance(8_000);
  expect(mockStartAnimating).not.toHaveBeenCalled();
  expect(complete).not.toHaveBeenCalled();
  await screen.rerender(<LaunchAlphaMotion playing onComplete={complete} />);
  expect(mockStartAnimating).toHaveBeenCalledTimes(1);
  await advance(2_000);
  await screen.rerender(<LaunchAlphaMotion playing={false} onComplete={complete} />);
  expect(mockStopAnimating).toHaveBeenCalledTimes(1);
  await advance(9_000);
  expect(complete).not.toHaveBeenCalled();
  await screen.rerender(<LaunchAlphaMotion playing onComplete={complete} />);
  expect(mockStartAnimating).toHaveBeenCalledTimes(2);
  await advance(2_999);
  expect(complete).not.toHaveBeenCalled();
  await advance(1);
  expect(complete).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('releases the launch when the image decoder never loads instead of blocking app access', async () => {
  const complete = jest.fn();
  const screen = await render(<LaunchAlphaMotion playing onComplete={complete} />);
  await advance(2_499);
  expect(complete).not.toHaveBeenCalled();
  await advance(1);
  expect(complete).toHaveBeenCalledTimes(1);
  expect(mockStartAnimating).not.toHaveBeenCalled();
  await screen.unmount();
});

test.each(['load failure', 'native play rejection'])('releases the launch on %s without leaking a late completion', async (failure) => {
  const complete = jest.fn();
  if (failure === 'native play rejection') mockStartAnimating.mockRejectedValueOnce(new Error('Decoder unavailable'));
  const screen = await render(<LaunchAlphaMotion playing onComplete={complete} />);
  await fireEvent(screen.getByTestId('launch-alpha-motion'), failure === 'load failure' ? 'error' : 'load');
  expect(complete).toHaveBeenCalledTimes(1);
  await screen.unmount();
  await advance(10_000);
  expect(complete).toHaveBeenCalledTimes(1);
});

test('cancels pending image playback when the launch is unmounted', async () => {
  const complete = jest.fn();
  const screen = await render(<LaunchAlphaMotion playing onComplete={complete} />);
  await fireEvent(screen.getByTestId('launch-alpha-motion'), 'load');
  await advance(1_000);
  await screen.unmount();
  await advance(10_000);
  expect(mockStopAnimating).toHaveBeenCalledTimes(1);
  expect(complete).not.toHaveBeenCalled();
});
