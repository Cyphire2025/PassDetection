import { onlineManager } from '@tanstack/react-query';
import { mobileQueryClient } from '../query-client';

jest.mock('@/core/config/env', () => ({ env: { demoModeRequested: true } }));

it('runs local demo queries when Android reports no internet connection', async () => {
  onlineManager.setOnline(false);
  const localQuery = jest.fn(async () => ({ passengerCount: 14 }));
  try {
    expect(mobileQueryClient.getDefaultOptions().mutations?.networkMode).toBe('always');
    expect(await mobileQueryClient.fetchQuery({ queryKey: ['offline-demo-roster'], queryFn: localQuery })).toEqual({ passengerCount: 14 });
    expect(localQuery).toHaveBeenCalledTimes(1);
  } finally {
    mobileQueryClient.clear();
    onlineManager.setOnline(true);
  }
});
