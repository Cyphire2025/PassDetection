import type { MobileRole } from '@/core/auth/types';

// Public sample-account values, never credentials for the live dashboard.
export const DEMO_PASSENGER_PHONE = '+919876543219';
export const DEMO_PASSENGER_OTP = '123456';
export const DEMO_STAFF_PASSWORD = 'Test@12345';
export const DEMO_OTP_CHALLENGE = 'standalone-demo-passenger';

export function demoStaffRole(email: string, password: string): Exclude<MobileRole, 'passenger'> | null {
  if (password !== DEMO_STAFF_PASSWORD) return null;
  switch (email.trim().toLowerCase()) {
    case 'coordinator@gmail.com': return 'coordinator';
    case 'clientmanager@gmail.com': return 'client_manager';
    default: return null;
  }
}

export function isDemoPassengerPhone(phone: string): boolean {
  return phone.replace(/[ ()-]/g, '') === DEMO_PASSENGER_PHONE;
}

export function isDemoPassengerOtp(challenge: string | null, phone: string, code: string): boolean {
  return challenge === DEMO_OTP_CHALLENGE && isDemoPassengerPhone(phone) && code === DEMO_PASSENGER_OTP;
}
