import { offlineSessionFromRow, shouldPurgePreviousNamespace } from '../offline-session';

const agencyId = '11111111-1111-4111-8111-111111111111';
const principalId = '22222222-2222-4222-8222-222222222222';
const namespace = `${agencyId}.${principalId}`;
const row = {
  id: principalId,
  agency_id: agencyId,
  principal_type: 'passenger' as const,
  display_name: 'Offline Passenger',
  session_id: '33333333-3333-4333-8333-333333333333',
  access_token_expires_at: '2026-08-02T00:10:00.000Z',
  refresh_token_expires_at: '2026-08-10T00:00:00.000Z',
  force_password_change: 0,
};

test('creates a locked-capable offline shell without an access token', () => {
  const session = offlineSessionFromRow(namespace, row, Date.parse('2026-08-03T00:00:00.000Z'));
  expect(session).toMatchObject({ accessToken: null, networkMode: 'offline', principal: { id: principalId } });
});

test('fails closed for namespace mismatch or expired refresh authority', () => {
  expect(offlineSessionFromRow(`${agencyId}.44444444-4444-4444-8444-444444444444`, row, 0)).toBeNull();
  expect(offlineSessionFromRow(namespace, row, Date.parse('2026-08-11T00:00:00.000Z'))).toBeNull();
});

test('account switching purges only a different previous namespace', () => {
  expect(shouldPurgePreviousNamespace(namespace, namespace)).toBe(false);
  expect(shouldPurgePreviousNamespace(null, namespace)).toBe(false);
  expect(shouldPurgePreviousNamespace('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', namespace)).toBe(true);
});
