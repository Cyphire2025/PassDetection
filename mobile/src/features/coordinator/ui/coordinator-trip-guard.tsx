import { usePathname, useRouter } from 'expo-router';
import { useEffect } from 'react';

import { LoadingScreen } from '@/design/components/loading-screen';

import { useCoordinatorTrips } from '../hooks/use-coordinator-trips';

export function CoordinatorTripGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const trips = useCoordinatorTrips();
  const onTripsScreen = pathname.endsWith('/groups');
  const mustChooseTrip = !trips.isPending && !trips.selectedTripId && !onTripsScreen;

  useEffect(() => {
    if (!mustChooseTrip) return;
    router.replace({
      pathname: '/(coordinator)/(tabs)/groups',
      params: { notice: 'select-group' },
    });
  }, [mustChooseTrip, router]);

  if (mustChooseTrip) return <LoadingScreen label="Select a group to continue" />;
  return children;
}
