import { isAccessLeaseExpired } from '../access-expiry-policy';

const expiresAt = '2026-08-12T10:00:00.000Z';

test('retains an unexpired offline access lease', () => {
  expect(isAccessLeaseExpired({
    accessExpiresAt: expiresAt,
    lastServerTime: '2026-08-12T08:00:00.000Z',
  }, Date.parse('2026-08-12T09:00:00.000Z'))).toBe(false);
});
test('expires a lease while foregrounded without a network request', () => {
  expect(isAccessLeaseExpired({
    accessExpiresAt: expiresAt,
    lastServerTime: '2026-08-12T08:00:00.000Z',
  }, Date.parse('2026-08-12T10:00:00.000Z'))).toBe(true);
});

test('fails closed for a rolled-back clock or malformed server clock', () => {
  expect(isAccessLeaseExpired({
    accessExpiresAt: expiresAt,
    lastServerTime: '2026-08-12T09:00:00.000Z',
  }, Date.parse('2026-08-12T08:00:00.000Z'))).toBe(true);
  expect(isAccessLeaseExpired({
    accessExpiresAt: expiresAt,
    lastServerTime: 'invalid',
  }, Date.parse('2026-08-12T09:00:00.000Z'))).toBe(true);
});
