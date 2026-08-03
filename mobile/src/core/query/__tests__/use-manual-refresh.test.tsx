import { act, renderHook } from '@testing-library/react-native';

import { useManualRefresh } from '../use-manual-refresh';

describe('useManualRefresh', () => {
  it('shows progress only while an explicit refresh action is running', async () => {
    let complete!: () => void;
    const action = jest.fn(() => new Promise<void>((resolve) => {
      complete = resolve;
    }));
    const { result } = await renderHook(() => useManualRefresh());

    expect(result.current.isRefreshing).toBe(false);
    let request!: Promise<void>;
    await act(async () => {
      request = result.current.refresh(action);
      await Promise.resolve();
    });

    expect(result.current.isRefreshing).toBe(true);
    expect(action).toHaveBeenCalledTimes(1);

    await act(async () => {
      complete();
      await request;
    });
    expect(result.current.isRefreshing).toBe(false);
  });

  it('deduplicates overlapping pulls and always clears after failure', async () => {
    let reject!: (error: Error) => void;
    const action = jest.fn(() => new Promise<void>((_resolve, rejectPromise) => {
      reject = rejectPromise;
    }));
    const { result } = await renderHook(() => useManualRefresh());

    let first!: Promise<void>;
    let second!: Promise<void>;
    await act(async () => {
      first = result.current.refresh(action);
      second = result.current.refresh(action);
      await Promise.resolve();
    });
    expect(second).toBe(first);
    expect(action).toHaveBeenCalledTimes(1);

    await act(async () => {
      reject(new Error('offline'));
      await first;
    });
    expect(action).toHaveBeenCalledTimes(1);
    expect(result.current.isRefreshing).toBe(false);
  });
});
