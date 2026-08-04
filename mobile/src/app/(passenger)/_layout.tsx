import { Redirect, Stack, usePathname } from 'expo-router';

import { navigationAnimation, useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { LoadingScreen } from '@/design/components/loading-screen';
import { RoleGate } from '@/design/navigation/role-gate';
import { passengerTripGateDecision } from '@/features/trips/data/passenger-trip-gate';
import { useTrips } from '@/features/trips/hooks/use-trips';

function PassengerTripGate() {
  const pathname = usePathname();
  const reduceMotion = useReducedMotion();
  const trips = useTrips();
  const decision = passengerTripGateDecision({
    isSelectorRoute: pathname.includes('/select-trip'),
    isError: trips.isError,
    selectionResolved: trips.selectionResolved,
    tripCount: trips.trips.length,
    selectedTripId: trips.selectedTripId,
  });
  if (decision === 'loading') return <LoadingScreen label="Opening your trip" />;
  if (decision === 'select') return <Redirect href="/(passenger)/select-trip" />;
  return (
    <Stack screenOptions={{ headerShown: false, animation: navigationAnimation(reduceMotion, 'slide_from_right') }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="select-trip" />
      <Stack.Screen name="document/[id]" />
    </Stack>
  );
}

export default function PassengerLayout() {
  return (
    <RoleGate role="passenger">
      <PassengerTripGate />
    </RoleGate>
  );
}
