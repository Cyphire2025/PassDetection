import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { parseIanaTimeZone } from '@/core/localization/time-zone';
import type { Trip } from '@/features/trips/model/trip';

import { resolveJourneyRoute } from '../../model';
import type { GlobeSurfaceHandle, GlobeSurfaceProps } from '../globe-surface';
import { JourneyGlobeControls } from '../journey-globe-controls';
import { JourneyGlobeModal } from '../journey-globe-modal';
import { JourneyRouteDetails } from '../journey-route-details';
import { TripJourneyCard } from '../trip-journey-card';

const mockZoomIn = jest.fn();
const mockZoomOut = jest.fn();
const mockReset = jest.fn();

jest.mock('lucide-react-native/icons/arrow-right', () => () => null);
jest.mock('lucide-react-native/icons/arrow-up-right', () => () => null);
jest.mock('lucide-react-native/icons/earth', () => () => null);
jest.mock('lucide-react-native/icons/locate-fixed', () => () => null);
jest.mock('lucide-react-native/icons/minus', () => () => null);
jest.mock('lucide-react-native/icons/plane', () => () => null);
jest.mock('lucide-react-native/icons/plus', () => () => null);
jest.mock('lucide-react-native/icons/x', () => () => null);
jest.mock('expo-status-bar', () => ({ StatusBar: () => null }));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: jest.requireActual('react-native').View }));
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 24, bottom: 16, left: 0, right: 0 }),
}));
jest.mock('react-native-gesture-handler', () => ({
  GestureHandlerRootView: jest.requireActual('react-native').View,
}));
jest.mock('@/design/accessibility/use-accessibility-route-focus', () => ({
  moveAccessibilityFocus: jest.fn(async () => false),
  useAccessibilityRouteFocus: jest.fn(),
}));
jest.mock('@/design/accessibility/use-reduced-motion', () => ({ useReducedMotion: () => true }));
jest.mock('@/design/components/offline-status-chip', () => ({ OfflineStatusChip: () => null }));
jest.mock('../../hooks/use-journey-route', () => ({
  useJourneyRoute: (selectedTrip: Trip) => ({
    route: jest.requireActual('../../model').resolveJourneyRoute(selectedTrip), status: 'resolved',
  }),
}));

// Exercise the actual modal's state/control wiring. Animation timing and GPU output
// are native verification concerns; this inert boundary completes transitions.
jest.mock('react-native-reanimated', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const { View } = jest.requireActual<typeof import('react-native')>('react-native');
  return {
    __esModule: true,
    default: { View },
    Easing: { bezier: jest.fn(), inOut: jest.fn(), cubic: jest.fn() },
    interpolate: (value: number, input: number[], output: number[]) => (
      value >= input[input.length - 1]! ? output[output.length - 1] : output[0]
    ),
    runOnJS: (callback: (...args: unknown[]) => unknown) => callback,
    useAnimatedStyle: (factory: () => unknown) => factory(),
    useSharedValue: (value: number) => React.useRef({
      value,
      set(next: number) { this.value = next; },
    }).current,
    withTiming: (value: number, _options: unknown, complete?: (finished: boolean) => void) => {
      complete?.(true);
      return value;
    },
  };
});

jest.mock('../globe-surface', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const { View } = jest.requireActual<typeof import('react-native')>('react-native');
  return {
    GlobeSurface: React.forwardRef<GlobeSurfaceHandle, GlobeSurfaceProps>(function MockGlobe(props, ref) {
      React.useImperativeHandle(ref, () => ({
        zoomIn: mockZoomIn, zoomOut: mockZoomOut, resetView: mockReset,
      }));
      return React.createElement(View, {
        testID: `mock-globe-${props.mode}`,
        accessibilityLabel: props.route?.destination.city ?? 'unmapped globe',
        accessibilityState: { disabled: !props.active },
        onTouchEnd: props.onReady,
        onTouchCancel: props.onError,
      });
    }),
  };
});

function trip(destination: string | null, id = 'trip-one'): Trip {
  return {
    id, name: 'Leadership visit', destination,
    travelDate: '2026-09-15', returnDate: '2026-09-20',
    timeZone: parseIanaTimeZone('Asia/Kolkata'), role: 'passenger',
    accessGeneration: 1, accessExpiresAt: null, itineraryVersion: 1,
    commonDocumentVersion: 1, announcementVersion: 1,
    updatedAt: '2026-09-07T00:00:00.000Z',
  };
}

const bounds = { x: 20, y: 100, width: 340, height: 206, globeSize: 246 };

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

test('shows destination-specific endpoints and identifies the assumed route', async () => {
  const result = await render(<JourneyRouteDetails route={resolveJourneyRoute(trip('Australia'))} />);
  expect(screen.getByText('SYD')).toBeOnTheScreen();
  expect(screen.getByText('Sydney')).toBeOnTheScreen();
  expect(screen.getByText('Australia')).toBeOnTheScreen();
  expect(screen.getByText('New Delhi')).toBeOnTheScreen();
  expect(screen.getByText(/Illustrative route/)).toBeOnTheScreen();
  expect(screen.getByText(/Your confirmed flight may differ/)).toBeOnTheScreen();

  await result.rerender(<JourneyRouteDetails route={resolveJourneyRoute(trip('Dubai', 'trip-two'))} />);
  expect(screen.getByText('DXB')).toBeOnTheScreen();
  expect(screen.getByText('Dubai')).toBeOnTheScreen();
  expect(screen.queryByText('Sydney')).toBeNull();
});

test('keeps an unknown destination useful without showing invented endpoints', async () => {
  await render(<JourneyRouteDetails route={null} />);
  expect(screen.getByText('A world to discover')).toBeOnTheScreen();
  expect(screen.getByText(/destination lookup is available/)).toBeOnTheScreen();
  expect(screen.queryByTestId('journey-route-details')).toBeNull();
  expect(screen.queryByText('DEL')).toBeNull();
});

test('never describes an animated confirmed route as live tracking', async () => {
  const route = resolveJourneyRoute(trip('Singapore'))!;
  await render(<JourneyRouteDetails route={{ ...route, kind: 'flight' }} />);
  expect(screen.getByText(/not live flight tracking/)).toBeOnTheScreen();
  expect(screen.queryByText(/Delhi departure/)).toBeNull();
});

test('exposes distinct accessible controls and invokes the matching callback', async () => {
  const onZoomIn = jest.fn();
  const onZoomOut = jest.fn();
  const onReset = jest.fn();
  await render(<JourneyGlobeControls onZoomIn={onZoomIn} onZoomOut={onZoomOut} onReset={onReset} />);
  await fireEvent.press(screen.getByRole('button', { name: 'Zoom in on globe' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Zoom out on globe' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Reset globe to your route' }));
  expect(onZoomIn).toHaveBeenCalledTimes(1);
  expect(onZoomOut).toHaveBeenCalledTimes(1);
  expect(onReset).toHaveBeenCalledTimes(1);
});

test('wires expanded controls to the globe handle and completes close once', async () => {
  const onClose = jest.fn();
  await render(
    <JourneyGlobeModal bounds={bounds} route={resolveJourneyRoute(trip('Dubai'))}
      title="Dubai" groupName="Leadership visit" reduceMotion onClose={onClose} />,
  );
  await fireEvent(screen.getByTestId('mock-globe-expanded'), 'touchEnd');
  await fireEvent.press(screen.getByRole('button', { name: 'Zoom in on globe' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Zoom out on globe' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Reset globe to your route' }));
  expect(mockZoomIn).toHaveBeenCalledTimes(1);
  expect(mockZoomOut).toHaveBeenCalledTimes(1);
  expect(mockReset).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Your confirmed flight may differ/)).toBeOnTheScreen();
  const close = screen.getByRole('button', { name: 'Close journey globe' });
  await fireEvent.press(close);
  await fireEvent.press(close);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('still exposes route details and dismissal when the GPU boundary fails', async () => {
  const onClose = jest.fn();
  await render(
    <JourneyGlobeModal bounds={bounds} route={resolveJourneyRoute(trip('Australia'))}
      title="Australia" groupName="Leadership visit" reduceMotion onClose={onClose} />,
  );
  await fireEvent(screen.getByTestId('mock-globe-expanded'), 'touchCancel');
  expect(screen.getByText(/Globe unavailable on this device/)).toBeOnTheScreen();
  expect(screen.getByText('Sydney')).toBeOnTheScreen();
  expect(screen.queryByRole('button', { name: 'Zoom in on globe' })).toBeNull();
  await fireEvent.press(screen.getByRole('button', { name: 'Close journey globe' }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('opens the unknown-destination fallback after readiness without inventing a route', async () => {
  const result = await render(
    <JourneyGlobeModal bounds={bounds} route={null} title="Atlantis"
      groupName="Leadership visit" reduceMotion onClose={jest.fn()} />,
  );
  await fireEvent(screen.getByTestId('mock-globe-expanded'), 'touchEnd');
  expect(screen.getByText('A world to discover')).toBeOnTheScreen();
  expect(screen.queryByText('DEL')).toBeNull();
  await result.unmount();
  await act(async () => { jest.runOnlyPendingTimers(); });
});

test('a missing GL callback settles into usable fallback and late readiness recovers controls', async () => {
  await render(
    <JourneyGlobeModal bounds={bounds} route={resolveJourneyRoute(trip('Singapore'))}
      title="Singapore" groupName="Leadership visit" reduceMotion onClose={jest.fn()} />,
  );
  await act(async () => { jest.advanceTimersByTime(1_500); });
  expect(screen.getByText(/Globe unavailable on this device/)).toBeOnTheScreen();
  expect(screen.getByText('SIN')).toBeOnTheScreen();
  expect(screen.queryByRole('button', { name: 'Zoom in on globe' })).toBeNull();
  await fireEvent(screen.getByTestId('mock-globe-expanded'), 'touchEnd');
  expect(screen.queryByText(/Globe unavailable on this device/)).toBeNull();
  expect(screen.getByRole('button', { name: 'Zoom in on globe' })).toBeOnTheScreen();
});

test('updates the card route and globe activity when its group or visibility changes', async () => {
  const result = await render(<TripJourneyCard trip={trip('Australia')} active />);
  expect(screen.getByRole('button', { name: 'Explore your journey to Australia' }))
    .toBeOnTheScreen();
  expect(screen.getByText(/DEL.*SYD/)).toBeOnTheScreen();
  const globe = () => screen.getByTestId('mock-globe-card', { includeHiddenElements: true });
  expect(globe().props.accessibilityState.disabled).toBe(false);

  await result.rerender(<TripJourneyCard trip={trip('Dubai', 'trip-two')} active={false} />);
  expect(screen.getByRole('button', { name: 'Explore your journey to Dubai' })).toBeOnTheScreen();
  expect(screen.getByText(/DEL.*DXB/)).toBeOnTheScreen();
  expect(screen.queryByText(/SYD/)).toBeNull();
  expect(globe().props.accessibilityState.disabled).toBe(true);

  await result.rerender(<TripJourneyCard trip={trip('Atlantis', 'trip-three')} active />);
  expect(screen.getByText('Discover your destination')).toBeOnTheScreen();
  expect(screen.queryByText(/DEL.*DXB/)).toBeNull();
});
