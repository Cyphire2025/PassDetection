import { act, renderHook } from '@testing-library/react-native';

import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from '../use-debounced-value';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

test('publishes only the last value after a fixed quiet window', async () => {
  const { result, rerender } = await renderHook(
    ({ value }: { value: string }) => useDebouncedValue(value),
    { initialProps: { value: '' } },
  );

  await rerender({ value: 'n' });
  await act(() => jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1));
  expect(result.current).toBe('');
  await rerender({ value: 'ni' });
  await act(() => jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
  expect(result.current).toBe('ni');
});
