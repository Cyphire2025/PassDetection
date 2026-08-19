import type { Trip } from '../../model/trip';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';
import {
  eligiblePassengerTrip,
  passengerTripDestination,
  passengerTripForRequiredPreload,
} from '../passenger-trip-selection';

const PASSENGER_TRIP: Trip = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Vietnam Group',
  destination: 'Vietnam',
  travelDate: '2026-08-12',
  returnDate: '2026-08-15',
  timeZone: DEFAULT_TRIP_TIME_ZONE,
  role: 'passenger',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-08-03T00:00:00.000Z',
};

test('only resolves a trip from the passenger account assignment list', () => {
  expect(eligiblePassengerTrip([PASSENGER_TRIP], PASSENGER_TRIP.id)).toEqual(PASSENGER_TRIP);
  expect(eligiblePassengerTrip([PASSENGER_TRIP], '22222222-2222-4222-8222-222222222222')).toBeNull();
  expect(eligiblePassengerTrip([{ ...PASSENGER_TRIP, role: 'client_manager' }], PASSENGER_TRIP.id)).toBeNull();
  expect(eligiblePassengerTrip([PASSENGER_TRIP], null)).toBeNull();
});

test('notification destinations stay inside passenger routes', () => {
  expect(passengerTripDestination('documents')).toBe('/(passenger)/(tabs)/documents');
  expect(passengerTripDestination('qr')).toBe('/(passenger)/(tabs)/qr');
  expect(passengerTripDestination('updates')).toBe('/(passenger)/(tabs)/updates');
  expect(passengerTripDestination('attendance')).toBe('/(passenger)/(tabs)/trip');
  expect(passengerTripDestination(undefined)).toBe('/(passenger)/(tabs)/trip');
});

test('requires an explicit choice when a passenger has multiple eligible trips', () => {
  const secondTrip = {
    ...PASSENGER_TRIP,
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Second Group',
  };
  expect(passengerTripForRequiredPreload([PASSENGER_TRIP])).toEqual(PASSENGER_TRIP);
  expect(passengerTripForRequiredPreload([PASSENGER_TRIP, secondTrip])).toBeNull();
  expect(passengerTripForRequiredPreload([PASSENGER_TRIP, secondTrip], secondTrip.id)).toEqual(secondTrip);
  expect(passengerTripForRequiredPreload([PASSENGER_TRIP], secondTrip.id)).toBeNull();
});
