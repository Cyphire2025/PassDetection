import {
  discardSupersededPhotoStaging,
  type PhotoDeliveryIdentity,
} from '../photo-delivery-identity';

const identity: PhotoDeliveryIdentity = {
  deliveryVersion: 7,
  expectedSizeBytes: 16_777_253,
  checksumSha256: 'a'.repeat(64),
  contentType: 'image/jpeg',
};

describe('photo delivery refresh identity', () => {
  it('preserves encrypted progress when an expired grant refreshes the same content version', async () => {
    const discard = jest.fn(async () => undefined);
    await expect(discardSupersededPhotoStaging(identity, { ...identity }, discard)).resolves.toBe(false);
    expect(discard).not.toHaveBeenCalled();
  });

  it.each([
    { deliveryVersion: 8 },
    { expectedSizeBytes: identity.expectedSizeBytes + 1 },
    { checksumSha256: 'b'.repeat(64) },
    { contentType: 'image/png' as const },
  ])('deletes old staging before adopting changed content metadata %#', async (change) => {
    const discard = jest.fn(async () => undefined);
    await expect(discardSupersededPhotoStaging(
      identity,
      { ...identity, ...change },
      discard,
    )).resolves.toBe(true);
    expect(discard).toHaveBeenCalledTimes(1);
  });
});
