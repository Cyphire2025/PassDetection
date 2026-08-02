import { useAuthFlowStore } from '../auth-flow-store';

beforeEach(() => useAuthFlowStore.getState().reset());

test('keeps only bounded authentication flow state and clears it after activation', () => {
  useAuthFlowStore.getState().setPhoneNumber('+919876543210');
  useAuthFlowStore.getState().setChallenge({
    challengeId: '11111111-1111-4111-8111-111111111111',
    expiresInSeconds: 300,
    resendAfterSeconds: 30,
  });
  expect(useAuthFlowStore.getState()).toMatchObject({
    phoneNumber: '+919876543210',
    resendAfterSeconds: 30,
  });
  useAuthFlowStore.getState().reset();
  expect(useAuthFlowStore.getState()).toMatchObject({ phoneNumber: '', challengeId: null, claims: [] });
});
