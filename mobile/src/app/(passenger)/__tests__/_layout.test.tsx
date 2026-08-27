import { render } from '@testing-library/react-native';
import { onlineManager } from '@tanstack/react-query';
import type { PropsWithChildren, ReactNode } from 'react';

import PassengerLayout from '../_layout';

let mockPathname = '/my-photos/photo/asset-a';
let mockFeatureEnabled: boolean | null = false;
let mockRedirectHref: string | null = null;
let mockStackScreenNames: string[] = [];

jest.mock('expo-router', () => {
  const Stack = ({ children }: PropsWithChildren): ReactNode => children;
  const StackScreen = ({ name }: { name: string }) => {
    mockStackScreenNames.push(name);
    return null;
  };
  Stack.Screen = StackScreen;
  return {
    Redirect: ({ href }: { href: string }) => {
      mockRedirectHref = href;
      return null;
    },
    Stack,
    usePathname: () => mockPathname,
  };
});

jest.mock('@/design/accessibility/use-reduced-motion', () => ({
  navigationAnimation: jest.fn(() => 'none'),
  useReducedMotion: jest.fn(() => true),
}));
jest.mock('@/design/components/loading-screen', () => ({
  LoadingScreen: () => null,
}));
jest.mock('@/design/navigation/role-gate', () => ({
  RoleGate: ({ children }: PropsWithChildren) => children,
}));
jest.mock('@/features/trips/hooks/use-trips', () => ({
  useTrips: () => ({
    isError: false,
    selectionResolved: true,
    trips: [{ id: '11111111-1111-4111-8111-111111111111' }],
    selectedTripId: '11111111-1111-4111-8111-111111111111',
  }),
}));
jest.mock('@/features/my-photos/hooks/use-my-photos', () => ({
  useMyPhotosSummary: () => ({
    data: mockFeatureEnabled === null
      ? undefined
      : {
          source: 'network',
          value: {
            capability: { feature_enabled: mockFeatureEnabled },
            experience_state: mockFeatureEnabled ? 'matches_ready' : 'feature_unavailable',
          },
        },
    error: null,
  }),
}));

beforeEach(() => {
  onlineManager.setOnline(true);
  mockPathname = '/my-photos/photo/asset-a';
  mockFeatureEnabled = false;
  mockRedirectHref = null;
  mockStackScreenNames = [];
});

test.each([false, null])(
  'redirects a direct My Photos deep link when capability is %s',
  async (featureEnabled) => {
    mockFeatureEnabled = featureEnabled;
    await render(<PassengerLayout />);
    expect(mockRedirectHref).toBe('/(passenger)/(tabs)/trip');
  },
);

test('allows the My Photos stack only after a fresh enabled summary', async () => {
  mockFeatureEnabled = true;
  await render(<PassengerLayout />);
  expect(mockRedirectHref).toBeNull();
  expect(mockStackScreenNames).toContain('my-photos/index');
});

test('does not block an unrelated passenger route', async () => {
  mockPathname = '/trip';
  mockFeatureEnabled = null;
  await render(<PassengerLayout />);
  expect(mockRedirectHref).toBeNull();
});
