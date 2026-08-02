import assert from "node:assert/strict";
import test from "node:test";
import {
  groupRoomingRosterPassengers,
  ROOMING_NOT_PROVIDED_KEY,
  roomingRosterValueKey,
  roomingRosterValueOptions,
  sortRoomingRosterPassengers,
} from "./rooming-roster-grouping.ts";

const passengers = [
  { passenger_id: "p10", client_name: "Álvaro 10" },
  { passenger_id: "p2", client_name: "Álvaro 2" },
  { passenger_id: "p3", client_name: "Élodie" },
  { passenger_id: "p4", client_name: "Zoë" },
];

test("rooming roster sorting is stable, Unicode-aware, and numeric", () => {
  assert.deepEqual(
    sortRoomingRosterPassengers(passengers).map(
      (passenger) => passenger.passenger_id,
    ),
    ["p2", "p10", "p3", "p4"],
  );
  assert.deepEqual(
    sortRoomingRosterPassengers(passengers, "desc").map(
      (passenger) => passenger.passenger_id,
    ),
    ["p4", "p3", "p10", "p2"],
  );
});

test("grouping merges case and whitespace variants and keeps missing last", () => {
  const values = {
    p10: "  Süd  Zone ",
    p2: "süd zone",
    p3: "North",
    p4: null,
  };
  const groups = groupRoomingRosterPassengers(passengers, values);

  assert.deepEqual(
    groups.map((group) => [group.key, group.passengers.length]),
    [
      ["north", 1],
      ["süd zone", 2],
      [ROOMING_NOT_PROVIDED_KEY, 1],
    ],
  );
  assert.equal(groups.at(-1)?.label, "Not provided");
  assert.equal(roomingRosterValueKey(" SÜD   ZONE "), "süd zone");
  assert.deepEqual(
    roomingRosterValueOptions(passengers, values).map(
      ({ key, count }) => [key, count],
    ),
    [
      ["north", 1],
      ["süd zone", 2],
      [ROOMING_NOT_PROVIDED_KEY, 1],
    ],
  );
});
