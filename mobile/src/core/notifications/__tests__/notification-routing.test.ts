import {
  isAssignedNotificationTrip,
  notificationAccountKey,
  notificationDestination,
  notificationResponseKey,
} from '../notification-routing';

const tripId = '11111111-1111-4111-8111-111111111111';
const eventId = '22222222-2222-4222-8222-222222222222';

describe('notification routing isolation', () => {
  it('namespaces the same principal independently for each agency', () => {
    const accountId = '33333333-3333-4333-8333-333333333333';
    expect(notificationAccountKey({ agencyId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', accountId }))
      .not.toBe(notificationAccountKey({ agencyId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', accountId }));
  });

  it('keeps notification deduplication stable when a passenger trip identity rotates', () => {
    const principal = {
      agencyId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      accountId: '33333333-3333-4333-8333-333333333333',
    };
    expect(notificationAccountKey(principal)).toBe(notificationAccountKey({ ...principal }));
  });

  it('maps only role-owned routes and falls back to the role group screen', () => {
    expect(notificationDestination('client_manager', 'readiness')).toBe('/(manager)/(tabs)/readiness');
    expect(notificationDestination('client_manager', 'attendance')).toBe('/(manager)/(tabs)/groups');
    expect(notificationDestination('coordinator', 'attendance')).toBe('/(coordinator)/(tabs)/attendance');
    expect(notificationDestination('coordinator', 'documents')).toBe('/(coordinator)/(tabs)/groups');
    expect(notificationDestination('passenger', 'qr')).toBe('/(passenger)/select-trip');
  });

  it('prefers a server event id and otherwise requires a bounded request id', () => {
    const data = { route: 'updates' as const, trip_id: tripId, event_id: eventId };
    expect(notificationResponseKey(data, 'request-1')).toBe(`event:${eventId}`);
    expect(notificationResponseKey({ route: 'updates', trip_id: tripId }, ' request-2 '))
      .toBe('request:request-2');
    expect(notificationResponseKey({ route: 'updates', trip_id: tripId }, '')).toBeNull();
  });

  it('does not authorize an unassigned notification trip', () => {
    expect(isAssignedNotificationTrip([{ id: tripId }], tripId)).toBe(true);
    expect(isAssignedNotificationTrip([{ id: tripId }], eventId)).toBe(false);
  });
});
