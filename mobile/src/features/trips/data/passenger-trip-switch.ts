import { switchPassengerTripSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace, type MobileSession } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';
import {
  cancelRequiredPreparation,
  completeRequiredPreparation,
} from '@/core/sync/required-preparation-lease';
import { syncTrip } from '@/core/sync/sync-service';
import {
  preloadPassengerTrip,
  type PassengerPreloadProgress,
} from '@/features/content/data/passenger-preload';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import type { Trip } from '../model/trip';
import { eligiblePassengerTrip, rememberPassengerTrip } from './passenger-trip-selection';

type PassengerBoundary = Readonly<{
  sessionId: string;
  namespace: string;
  principalId: string;
  passengerId: string;
}>;

export type PassengerTripSwitchResult = Readonly<{
  tripId: string;
  usedPreparedCache: boolean;
  failedDownloads: number;
}>;

export type PassengerTripSwitchInput = Readonly<{
  tripId: string;
  trips: readonly Trip[];
  onBlockingPreparation: () => void;
  onProgress: (progress: PassengerPreloadProgress) => void;
}>;

type ActivePassengerTripSwitch = Readonly<{
  tripId: string;
  promise: Promise<PassengerTripSwitchResult>;
}>;

const activeSwitches = new Map<string, ActivePassengerTripSwitch>();

export class PassengerTripSwitchInProgressError extends Error {
  readonly code = 'PASSENGER_TRIP_SWITCH_IN_PROGRESS';

  constructor() {
    super('Another trip is already being opened.');
    this.name = 'PassengerTripSwitchInProgressError';
  }
}

function activeOnlinePassengerSession(): MobileSession {
  const session = useSessionStore.getState().session;
  if (
    !session
    || session.networkMode !== 'online'
    || session.principal.principalType !== 'passenger'
  ) {
    throw new Error('An online passenger session is required to switch trips.');
  }
  return session;
}

function passengerBoundary(session: MobileSession): PassengerBoundary {
  const passengerId = session.principal.passengerId;
  if (session.principal.principalType !== 'passenger' || !passengerId) {
    throw new Error('The passenger ownership boundary is unavailable. Sign in again while online.');
  }
  return Object.freeze({
    sessionId: session.sessionId,
    namespace: principalAccountNamespace(session.principal),
    principalId: session.principal.id,
    passengerId,
  });
}

function assertPassengerBoundaryActive(boundary: PassengerBoundary): void {
  const session = useSessionStore.getState().session;
  if (
    !session
    || session.networkMode !== 'online'
    || session.sessionId !== boundary.sessionId
    || session.principal.principalType !== 'passenger'
    || session.principal.id !== boundary.principalId
    || session.principal.passengerId !== boundary.passengerId
    || principalAccountNamespace(session.principal) !== boundary.namespace
  ) {
    throw new Error('The active mobile session changed while opening this trip.');
  }
}

/**
 * A cache is considered prepared only when a successful sync cursor and a QR
 * identity for this exact travel-passenger record coexist in the stable account
 * namespace. The QR ownership proof prevents a shared phone/account from
 * reusing another passenger's previously synchronized group cache.
 */
export async function hasPreparedPassengerTripCache(
  tripId: string,
  boundary: PassengerBoundary,
): Promise<boolean> {
  assertPassengerBoundaryActive(boundary);
  const database = await openAccountDatabase(boundary.namespace);
  assertPassengerBoundaryActive(boundary);
  const prepared = await database.getFirstAsync<{ prepared: number }>(
    `SELECT 1 AS prepared
       FROM trips trip
       JOIN sync_cursors cursor
         ON cursor.account_namespace = trip.account_namespace
        AND cursor.trip_id = trip.id
      WHERE trip.account_namespace = ?
        AND trip.id = ?
        AND trip.role = 'passenger'
        AND cursor.last_synced_at IS NOT NULL
        AND EXISTS (
          SELECT 1
            FROM qr_metadata qr
           WHERE qr.account_namespace = trip.account_namespace
             AND qr.trip_id = trip.id
             AND qr.passenger_id = ?
        )
        AND NOT EXISTS (
          SELECT 1
            FROM trip_purge_tombstones purge
           WHERE purge.account_namespace = trip.account_namespace
             AND purge.trip_id = trip.id
        )
      LIMIT 1`,
    boundary.namespace,
    tripId,
    boundary.passengerId,
  );
  assertPassengerBoundaryActive(boundary);
  return Boolean(prepared);
}

async function performPassengerTripSwitch(
  input: PassengerTripSwitchInput,
): Promise<PassengerTripSwitchResult> {
  // Reject identifier substitution before making a request. The switch API is
  // still the authoritative ownership check and rotates the selected identity.
  if (!eligiblePassengerTrip(input.trips, input.tripId)) {
    throw new Error('This trip is not assigned to the current passenger account.');
  }

  let switchedSessionId: string | null = null;
  let switchedBoundary: PassengerBoundary | null = null;
  try {
    const switchedSession = await switchPassengerTripSession(input.tripId);
    switchedSessionId = switchedSession.sessionId;
    // Never leave an old trip selected while the bearer token is already bound
    // to the newly authorized passenger identity. If any later preparation
    // step fails, the UI can show an empty/new-trip state but cannot read the
    // previous group's cache through a mismatched session.
    useSelectedTripStore.getState().clear();
    switchedBoundary = passengerBoundary(switchedSession);
    assertPassengerBoundaryActive(switchedBoundary);
    useSelectedTripStore.getState().selectTrip(input.tripId);

    const prepared = await hasPreparedPassengerTripCache(input.tripId, switchedBoundary);
    assertPassengerBoundaryActive(switchedBoundary);
    if (prepared) {
      await rememberPassengerTrip(input.trips, input.tripId);
      assertPassengerBoundaryActive(switchedBoundary);
      completeRequiredPreparation(switchedBoundary.sessionId);

      // Cache-first navigation is no longer coupled to the network refresh.
      // syncTrip already coalesces duplicate account/session/trip jobs and its
      // immutable context prevents a late result crossing another selection.
      void syncTrip(input.tripId).catch(() => undefined);
      return { tripId: input.tripId, usedPreparedCache: true, failedDownloads: 0 };
    }

    input.onBlockingPreparation();
    const result = await preloadPassengerTrip(input.onProgress, input.tripId);
    assertPassengerBoundaryActive(switchedBoundary);
    if (!result.tripId || result.tripId !== input.tripId || result.selectionRequired) {
      throw new Error('Please select an assigned trip before continuing.');
    }
    completeRequiredPreparation(switchedBoundary.sessionId);
    return {
      tripId: result.tripId,
      usedPreparedCache: false,
      failedDownloads: result.failedDownloads,
    };
  } catch (error) {
    if (switchedSessionId) {
      const active = useSessionStore.getState().session;
      if (active?.sessionId === switchedSessionId) {
        cancelRequiredPreparation(switchedSessionId);
      }
    }
    throw error;
  }
}

/**
 * Serializes trip-token rotation per stable passenger account. Repeated taps
 * for the same trip share one promise; a competing trip intent fails closed
 * instead of racing two token rotations and local selections.
 */
export function switchToPassengerTrip(
  input: PassengerTripSwitchInput,
): Promise<PassengerTripSwitchResult> {
  let session: MobileSession;
  try {
    session = activeOnlinePassengerSession();
  } catch (error) {
    return Promise.reject(error);
  }
  const key = `${principalAccountNamespace(session.principal)}:${session.sessionId}`;
  const active = activeSwitches.get(key);
  if (active) {
    if (active.tripId === input.tripId) return active.promise;
    return Promise.reject(new PassengerTripSwitchInProgressError());
  }

  const promise = performPassengerTripSwitch(input).finally(() => {
    if (activeSwitches.get(key)?.promise === promise) activeSwitches.delete(key);
  });
  activeSwitches.set(key, { tripId: input.tripId, promise });
  return promise;
}
