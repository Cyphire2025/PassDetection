import { useLocalSearchParams } from 'expo-router';

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { useCoordinatorPassenger } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';
import { OperationalPassengerDetail } from '@/features/coordinator/ui/operational-passenger-detail';

export default function CoordinatorPassengerDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const manualRefresh = useManualRefresh();
  const trips = useCoordinatorTrips();
  const detail = useCoordinatorPassenger(trips.selectedTripId, id ?? null);
  return (
    <OperationalPassengerDetail
      passenger={detail.data?.passenger}
      isPending={detail.isPending}
      isError={detail.isError}
      isRefreshing={manualRefresh.isRefreshing}
      onRefresh={() => void manualRefresh.refresh(detail.refetch)}
      subtitle={trips.selectedTrip?.name || 'Selected group'}
      timeZone={trips.selectedTrip?.timeZone}
      errorMessage="These passenger details are not authorized or available on this device."
    />
  );
}
