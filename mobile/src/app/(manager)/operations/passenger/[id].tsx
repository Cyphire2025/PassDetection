import { useLocalSearchParams } from 'expo-router';

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { OperationalPassengerDetail } from '@/features/coordinator/ui/operational-passenger-detail';
import { useManagerPassenger } from '@/features/manager/hooks/use-manager-operations';
import { useTrips } from '@/features/trips/hooks/use-trips';

export default function ManagerPassengerDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const manualRefresh = useManualRefresh();
  const trips = useTrips();
  const detail = useManagerPassenger(trips.selectedTripId, id ?? null);
  return (
    <OperationalPassengerDetail
      passenger={detail.data?.passenger}
      isPending={detail.isPending}
      isError={detail.isError}
      isRefreshing={manualRefresh.isRefreshing}
      onRefresh={() => void manualRefresh.refresh(detail.refetch)}
      subtitle={trips.selectedTrip?.name || 'Selected group'}
      timeZone={trips.selectedTrip?.timeZone}
      errorMessage="These passenger details are not authorized or available."
    />
  );
}
