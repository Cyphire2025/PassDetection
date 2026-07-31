import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  sanitizeOfflinePassengerSnapshots,
  toOfflinePassengerSnapshot,
} from "./passenger-offline-projection.ts";

const page = readFileSync(
  new URL("../components/coordinator-passenger-detail-page.tsx", import.meta.url),
  "utf8",
);
const activityPage = readFileSync(
  new URL("../components/coordinator-group-activity-page.tsx", import.meta.url),
  "utf8",
);

test("offline passenger snapshots contain only fields rendered by the detail page", () => {
  const snapshot = toOfflinePassengerSnapshot({
    id: "passenger-1",
    client_name: "Asha Singh",
    client_email: "asha@example.test",
    client_phone: "+919876543210",
    departure_city: "Delhi",
    status: "confirmed",
    coordinator_id: null,
    coordinator_name: null,
    passport_fields: {
      passport_number: "P1234567",
      mrz_raw: "P<IND...",
      image_s3_key: "private/passports/front.jpg",
    },
    overall_confidence: 0.99,
    mrz_raw: "P<IND...",
    image_s3_key: "private/passports/front.jpg",
    passport_photo_s3_key: "private/passports/photo.jpg",
  });

  assert.deepEqual(snapshot, {
    id: "passenger-1",
    client_name: "Asha Singh",
    client_email: "asha@example.test",
    client_phone: "+919876543210",
    departure_city: "Delhi",
  });
  for (const sensitiveField of [
    "passport_fields",
    "overall_confidence",
    "mrz_raw",
    "image_s3_key",
    "passport_photo_s3_key",
  ]) {
    assert.equal(sensitiveField in snapshot, false);
  }
});

test("legacy multi-passenger snapshots are fully sanitized before reuse", () => {
  const secretOne = "P1234567";
  const secretTwo = "P7654321";
  const snapshots = sanitizeOfflinePassengerSnapshots([
    {
      id: "passenger-1",
      client_name: "Asha Singh",
      client_email: "asha@example.test",
      client_phone: "+919876543210",
      departure_city: "Delhi",
      passport_fields: { passport_number: secretOne },
      overall_confidence: 0.99,
      mrz_raw: "P<IND...",
      image_s3_key: "private/passports/one.jpg",
    },
    {
      id: "passenger-2",
      client_name: "Vikram Shah",
      client_email: null,
      client_phone: "+919123456789",
      departure_city: "Mumbai",
      passport_fields: { passport_number: secretTwo },
      passport_photo_s3_key: "private/passports/two.jpg",
    },
  ]);

  assert.deepEqual(snapshots, [
    {
      id: "passenger-1",
      client_name: "Asha Singh",
      client_email: "asha@example.test",
      client_phone: "+919876543210",
      departure_city: "Delhi",
    },
    {
      id: "passenger-2",
      client_name: "Vikram Shah",
      client_email: null,
      client_phone: "+919123456789",
      departure_city: "Mumbai",
    },
  ]);
  const serialized = JSON.stringify(snapshots);
  for (const secret of [
    secretOne,
    secretTwo,
    "passport_fields",
    "overall_confidence",
    "mrz_raw",
    "image_s3_key",
    "passport_photo_s3_key",
  ]) {
    assert.equal(serialized.includes(secret), false);
  }
});

test("the passenger detail write path persists the explicit offline projection", () => {
  assert.match(page, /sanitizeOfflinePassengerSnapshots\(/);
  assert.match(page, /const offlinePassenger = toOfflinePassengerSnapshot\(passengerQuery\.data\)/);
  assert.match(
    page,
    /writeOfflineSnapshot\(passengerSnapshotKey, nextPassengers\)/,
  );
  assert.doesNotMatch(
    page,
    /writeOfflineSnapshot\([^;]*passengerQuery\.data/s,
  );
  assert.match(activityPage, /sanitizeOfflinePassengerSnapshots\(/);
  assert.match(
    activityPage,
    /passengers\.map\(\(passenger\) => toOfflinePassengerSnapshot\(passenger\)\)/,
  );
});
