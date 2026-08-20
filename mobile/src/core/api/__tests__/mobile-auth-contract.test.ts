import {
  OtpVerifyResponseSchema,
  TokenResponseSchema,
} from '@/core/api/contracts';

const principal = {
  id: '11111111-1111-4111-8111-111111111111',
  account_id: '22222222-2222-4222-8222-222222222222',
  principal_type: 'passenger' as const,
  agency_id: '33333333-3333-4333-8333-333333333333',
  passenger_id: '44444444-4444-4444-8444-444444444444',
  display_name: 'Contract Passenger',
  email: null,
  phone_number: null,
  force_password_change: false,
};

const tokens = {
  access_token: 'a'.repeat(64),
  refresh_token: 'r'.repeat(64),
  token_type: 'bearer' as const,
  access_token_expires_at: '2026-08-20T12:15:00.000Z',
  refresh_token_expires_at: '2026-09-19T12:00:00.000Z',
  session_id: '55555555-5555-4555-8555-555555555555',
  offline_authorization_lease: `${'a'.repeat(80)}.${'b'.repeat(120)}.${'c'.repeat(94)}`,
  principal,
};

describe('strict mobile authentication response contracts', () => {
  it('accepts the complete token response required by every token-issuance path', () => {
    expect(TokenResponseSchema.parse(tokens)).toEqual(tokens);
  });

  it('rejects the legacy production response that omitted the signed offline lease', () => {
    const { offline_authorization_lease: removedLease, ...legacyResponse } = tokens;

    expect(removedLease).toBeTruthy();
    expect(TokenResponseSchema.safeParse(legacyResponse).success).toBe(false);
  });

  it('accepts an authenticated OTP response only with complete tokens', () => {
    expect(OtpVerifyResponseSchema.parse({
      status: 'authenticated',
      claims: [],
      tokens,
    })).toEqual({ status: 'authenticated', claims: [], tokens });
  });

  it.each([
    { status: 'authenticated', claims: [], tokens: null },
    { status: 'authenticated', claims: [{ claim_id: principal.id }], tokens },
    { status: 'secondary_verification_required', claims: [], tokens },
    { status: 'claim_selection_required', claims: [], tokens: null },
  ])('rejects contradictory OTP status payloads: $status', (response) => {
    expect(OtpVerifyResponseSchema.safeParse(response).success).toBe(false);
  });
});
