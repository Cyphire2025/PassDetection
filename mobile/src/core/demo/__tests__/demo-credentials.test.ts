import { DEMO_OTP_CHALLENGE, demoStaffRole, isDemoPassengerOtp, isDemoPassengerPhone } from '../demo-credentials';

describe('fixed review credentials', () => {
  it('routes each staff login only to its assigned role', () => {
    expect(demoStaffRole('coordinator@gmail.com', 'Test@12345')).toBe('coordinator');
    expect(demoStaffRole(' CLIENTMANAGER@gmail.com ', 'Test@12345')).toBe('client_manager');
    expect(demoStaffRole('coordinator@gmail.com', 'Test@123456')).toBeNull();
    expect(demoStaffRole('other@gmail.com', 'Test@12345')).toBeNull();
  });
  it('accepts the fixed passenger phone and reusable code together', () => {
    expect(isDemoPassengerPhone('+91 98765 43219')).toBe(true);
    expect(isDemoPassengerOtp(DEMO_OTP_CHALLENGE, '+919876543219', '123456')).toBe(true);
    expect(isDemoPassengerOtp(DEMO_OTP_CHALLENGE, '+919876543219', '123456')).toBe(true);
    expect(isDemoPassengerOtp(null, '+919876543219', '123456')).toBe(false);
    expect(isDemoPassengerOtp(DEMO_OTP_CHALLENGE, '+919876543210', '123456')).toBe(false);
    expect(isDemoPassengerOtp(DEMO_OTP_CHALLENGE, '+919876543219', '000000')).toBe(false);
  });
});
