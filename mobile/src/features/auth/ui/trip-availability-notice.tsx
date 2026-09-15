import { PrimaryButton } from '@/design/components/primary-button';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export type TripAvailability = 'trip_not_active' | 'trip_starts_later' | 'trip_access_ended';

export function isTripAvailability(status: string): status is TripAvailability {
  return status === 'trip_not_active' || status === 'trip_starts_later' || status === 'trip_access_ended';
}

const messages: Record<TripAvailability, { title: string; description: string }> = {
  trip_not_active: {
    title: 'Your trip is not active in GC App yet.',
    description: 'Your WhatsApp number is verified. Your travel team needs to activate passenger access before you can open your trip. Please contact them or try again later.',
  },
  trip_starts_later: {
    title: 'Your trip access starts later.',
    description: 'Your WhatsApp number is verified. Passenger access is scheduled to open later. Please check with your travel team and sign in again when access opens.',
  },
  trip_access_ended: {
    title: 'Your trip access has ended.',
    description: 'Your WhatsApp number is verified. The access period has ended. Please contact your travel team if you still need access.',
  },
};

export function TripAvailabilityNotice({ status, onBack }: { status: TripAvailability; onBack: () => void }) {
  return (
    <AuthShell eyebrow="Number verified" {...messages[status]}>
      <PrimaryButton label="Back to sign in" onPress={onBack} />
    </AuthShell>
  );
}
