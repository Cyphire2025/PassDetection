import { classifyApiMetricOperation } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));

test.each([
  ['/mobile/auth/otp/verify', 'authentication'],
  ['/mobile/me', 'authentication'],
  ['/mobile/passengers/11111111-1111-4111-8111-111111111111/groups/22222222-2222-4222-8222-222222222222/my-photos/photos?cursor=secret', 'my_photos'],
  ['/mobile/coordinator/groups/11111111-1111-4111-8111-111111111111/attendance/actions', 'attendance'],
  ['/mobile/trips/11111111-1111-4111-8111-111111111111/documents', 'documents'],
  ['/mobile/trips/11111111-1111-4111-8111-111111111111/itinerary', 'itinerary'],
  ['/mobile/trips?cursor=opaque', 'trip_catalog'],
  ['/mobile/manager/groups/11111111-1111-4111-8111-111111111111/readiness', 'manager'],
  ['/health/live', 'health'],
] as const)('classifies %s into the fixed %s telemetry operation', (path, operation) => {
  expect(classifyApiMetricOperation(path)).toBe(operation);
});

test('does not create a metric dimension from unknown dynamic path content', () => {
  expect(classifyApiMetricOperation('/mobile/private/customer-secret-value')).toBe('other');
});
