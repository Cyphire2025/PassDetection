import {
  assertMyPhotosContextStillCurrent,
  type MyPhotosContext,
} from '../data/my-photos-context';
import { purgeMyPhotosPrivateTripData } from '../data/my-photos-repository';
import { photoDownloadExecutions } from './download-manager';
import { deletePhotoTripStorage } from './photo-vault';

/** Irreversibly closes local My Photos state for a server-confirmed disabled
 * passenger trip. The caller owns the runtime namespace fence so no producer
 * can recreate queue rows between native-transfer settlement and deletion. */
export async function purgeDisabledMyPhotosTrip(
  context: MyPhotosContext,
  signal: AbortSignal = context.signal,
): Promise<void> {
  const assertActive = () => {
    if (signal.aborted) {
      throw signal.reason instanceof Error
        ? signal.reason
        : new Error('My Photos feature-disable cleanup was cancelled.');
    }
    assertMyPhotosContextStillCurrent(context);
  };

  await photoDownloadExecutions.abortContextAndWait(
    context,
    new Error('My Photos was disabled for this trip.'),
  );
  assertActive();
  await deletePhotoTripStorage(context.namespace, context.tripId);
  assertActive();
  await purgeMyPhotosPrivateTripData(context, assertActive);
  assertActive();
}
