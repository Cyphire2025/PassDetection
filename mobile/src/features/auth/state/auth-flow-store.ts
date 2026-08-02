import { create } from 'zustand';

import type { z } from 'zod';

import type { TripClaimSchema } from '@/core/api/contracts';

type TripClaim = z.infer<typeof TripClaimSchema>;

type AuthFlowState = {
  phoneNumber: string;
  challengeId: string | null;
  challengeExpiresAt: number | null;
  resendAvailableAt: number | null;
  resendAfterSeconds: number;
  claims: TripClaim[];
  setPhoneNumber: (phoneNumber: string) => void;
  setChallenge: (input: {
    challengeId: string;
    expiresInSeconds: number;
    resendAfterSeconds: number;
  }) => void;
  setClaims: (claims: TripClaim[]) => void;
  reset: () => void;
};

export const useAuthFlowStore = create<AuthFlowState>((set) => ({
  phoneNumber: '',
  challengeId: null,
  challengeExpiresAt: null,
  resendAvailableAt: null,
  resendAfterSeconds: 0,
  claims: [],
  setPhoneNumber: (phoneNumber) => set({ phoneNumber }),
  setChallenge: ({ challengeId, expiresInSeconds, resendAfterSeconds }) => {
    const now = Date.now();
    set({
      challengeId,
      challengeExpiresAt: now + expiresInSeconds * 1000,
      resendAvailableAt: now + resendAfterSeconds * 1000,
      resendAfterSeconds,
    });
  },
  setClaims: (claims) => set({ claims }),
  reset: () =>
    set({
      phoneNumber: '',
      challengeId: null,
      challengeExpiresAt: null,
      resendAvailableAt: null,
      resendAfterSeconds: 0,
      claims: [],
    }),
}));
