export type PhotoDeliveryIdentity = Readonly<{
  deliveryVersion: number;
  expectedSizeBytes: number;
  checksumSha256: string;
  contentType: 'image/jpeg' | 'image/png' | 'image/webp';
}>;

export function photoDeliveryIdentityChanged(
  current: PhotoDeliveryIdentity,
  next: PhotoDeliveryIdentity,
): boolean {
  return current.deliveryVersion !== next.deliveryVersion
    || current.expectedSizeBytes !== next.expectedSizeBytes
    || current.checksumSha256 !== next.checksumSha256
    || current.contentType !== next.contentType;
}

/** Deletes a now-unreachable staging identity before manifest metadata moves
 * to a genuinely new content version. Grant-only refreshes retain staging. */
export async function discardSupersededPhotoStaging(
  current: PhotoDeliveryIdentity | null,
  next: PhotoDeliveryIdentity,
  discard: () => void | Promise<void>,
): Promise<boolean> {
  if (!current || !photoDeliveryIdentityChanged(current, next)) return false;
  await discard();
  return true;
}
