import { offlineSessionFromRow, shouldPurgePreviousNamespace } from '../offline-session';

const agencyId = '11111111-1111-4111-8111-111111111111';
const principalId = '22222222-2222-4222-8222-222222222222';
const namespace = `${agencyId}.${principalId}`;
const row = {
  id: principalId,
  account_id: principalId,
  agency_id: agencyId,
  principal_type: 'passenger' as const,
  passenger_id: '44444444-4444-4444-8444-444444444444',
  display_name: 'Offline Passenger',
  email: 'passenger@example.com',
  phone_number: '+919876543210',
  session_id: '33333333-3333-4333-8333-333333333333',
  access_token_expires_at: '2026-08-02T00:10:00.000Z',
  refresh_token_expires_at: '2026-08-10T00:00:00.000Z',
  force_password_change: 0,
};

test('creates an offline shell without requiring a second device unlock', () => {
  const session = offlineSessionFromRow(namespace, row);
  expect(session).toMatchObject({
    accessToken: null,
    networkMode: 'offline',
    principal: {
      id: principalId,
      accountId: principalId,
      passengerId: '44444444-4444-4444-8444-444444444444',
      email: 'passenger@example.com',
      phoneNumber: '+919876543210',
    },
  });
});

test('keeps the offline namespace stable after a passenger trip identity switch', () => {
  const switchedIdentityId = '55555555-5555-4555-8555-555555555555';
  const session = offlineSessionFromRow(
    namespace,
    { ...row, id: switchedIdentityId },
  );
  expect(session?.principal).toMatchObject({
    id: switchedIdentityId,
    accountId: principalId,
  });
});

test('fails closed for a namespace mismatch while leaving authorization to the signed lease', () => {
  expect(offlineSessionFromRow(`${agencyId}.44444444-4444-4444-8444-444444444444`, row)).toBeNull();
  expect(offlineSessionFromRow(namespace, {
    ...row,
    refresh_token_expires_at: '2020-01-01T00:00:00.000Z',
  })).not.toBeNull();
});

test('fails closed for a passenger snapshot without an authoritative passenger record', () => {
  expect(offlineSessionFromRow(namespace, { ...row, passenger_id: null })).toBeNull();
});

test('account switching purges only a different previous namespace', () => {
  expect(shouldPurgePreviousNamespace(namespace, namespace)).toBe(false);
  expect(shouldPurgePreviousNamespace(null, namespace)).toBe(false);
  expect(shouldPurgePreviousNamespace('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', namespace)).toBe(true);
});
