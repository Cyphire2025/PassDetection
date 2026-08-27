import type { MyPhotosSummary } from '../../api/contracts';
import { faceScanCapabilityBlock } from '../face-scan-capability-policy';

function capability(
  providerState: MyPhotosSummary['capability']['provider_state'],
): MyPhotosSummary['capability'] {
  return {
    feature_enabled: true,
    provider_ready: providerState === 'ready',
    provider_state: providerState,
    client_flow: providerState === 'not_configured' ? 'unavailable' : 'native',
    supported_challenge_modes: ['movement_and_light', 'movement_only'],
    retryable: providerState === 'temporarily_unavailable',
  };
}

it('distinguishes fail-closed not-configured from retryable provider unavailability', () => {
  expect(faceScanCapabilityBlock(capability('not_configured'))).toBe('provider_not_configured');
  expect(faceScanCapabilityBlock(capability('temporarily_unavailable')))
    .toBe('provider_temporarily_unavailable');
  expect(faceScanCapabilityBlock(capability('ready'))).toBeNull();
});
