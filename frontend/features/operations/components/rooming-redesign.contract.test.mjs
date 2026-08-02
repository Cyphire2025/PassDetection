import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  isRoomingPriorityFieldAllowed,
} from "./rooming-priority-field-policy.mjs";

const workspace = readFileSync(
  new URL("./rooming-workspace-page.tsx", import.meta.url),
  "utf8",
);
const passengerAllocation = readFileSync(
  new URL("./rooming-passenger-hotel-allocation.tsx", import.meta.url),
  "utf8",
);
const autoAllocation = readFileSync(
  new URL("./rooming-auto-allocation.tsx", import.meta.url),
  "utf8",
);
const errorMessage = readFileSync(
  new URL("./rooming-error-message.ts", import.meta.url),
  "utf8",
);
const priorityPolicy = readFileSync(
  new URL("./rooming-priority-field-policy.mjs", import.meta.url),
  "utf8",
);
const rosterGrouping = readFileSync(
  new URL("./rooming-roster-grouping.ts", import.meta.url),
  "utf8",
);
const api = readFileSync(
  new URL("../api/operations.api.ts", import.meta.url),
  "utf8",
);
const hooks = readFileSync(
  new URL("../hooks/use-operations.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);

test("manual room generation and drag allocation are removed from product UI", () => {
  assert.doesNotMatch(workspace, /Generate rooms|generateRooms|draggable|onDrop/);
  assert.doesNotMatch(
    workspace,
    /RoomingRoom|RoomType|RoomingTag|generateRoomingRooms|updateRoomingAllocation/,
  );
  assert.doesNotMatch(passengerAllocation, /Generate rooms|draggable|onDrop/);
  assert.doesNotMatch(
    endpoints,
    /generateRooms:|roomOrder:|^\s+room:\s+\(roomId|allocation:\s+\(hotelId/m,
  );
  assert.doesNotMatch(
    api,
    /generateRoomingRooms:|updateRoomingAllocation:|deleteRoomingRoom:|updateRoomingRoom:|updateRoomingRoomOrder:/,
  );
  assert.doesNotMatch(
    hooks,
    /generateRooms:\s+useMutation|allocatePassenger:\s+useMutation|deleteRoom:\s+useMutation|updateRoom:\s+useMutation|orderRooms:\s+useMutation/,
  );
  assert.doesNotMatch(api, /room_count/);
  assert.doesNotMatch(hooks, /room_count/);
  assert.match(workspace, /<RoomingPassengerHotelAllocation/);
  assert.match(workspace, /<RoomingAutoAllocation/);
});

test("passengers can be selected in bulk and moved safely between hotels", () => {
  assert.match(
    passengerAllocation,
    /const \[isExpanded, setIsExpanded\] = useState\(false\)/,
  );
  assert.match(passengerAllocation, /aria-expanded=\{isExpanded\}/);
  assert.match(passengerAllocation, /isExpanded && \(/);
  assert.match(passengerAllocation, /Show passenger list/);
  assert.match(passengerAllocation, /Select visible/);
  assert.match(passengerAllocation, /Select all group/);
  assert.match(passengerAllocation, /First passengers/);
  assert.match(passengerAllocation, /Select first/);
  assert.match(passengerAllocation, /type="checkbox"/);
  assert.match(
    passengerAllocation,
    /onTogglePassenger\(passenger\.passenger_id\)/,
  );
  assert.match(passengerAllocation, /Assign selected passengers to/);
  assert.match(passengerAllocation, /Current hotel/);
  assert.match(workspace, /mode: "add"/);
  assert.doesNotMatch(workspace, /mode: "replace"/);
  assert.match(endpoints, /passengerSelection:[\s\S]*?passenger-selection/);
  assert.match(hooks, /selectHotelPassengers:[\s\S]*?passenger_ids: passengerIds/);
});

test("imported fields group passengers in collapsible selectable sections", () => {
  assert.match(endpoints, /rosterFieldValues:[\s\S]*?roster-field-values/);
  assert.match(api, /roomingRosterFieldValues:[\s\S]*?field_key: fieldKey/);
  assert.match(hooks, /useRoomingRosterFieldValues/);
  assert.match(passengerAllocation, /Group by imported field/);
  assert.match(passengerAllocation, /Filter grouped value/);
  assert.match(passengerAllocation, /Passenger sort/);
  assert.match(passengerAllocation, /<RosterGroupSection/);
  assert.match(passengerAllocation, /<GroupSelectionCheckbox/);
  assert.match(passengerAllocation, /Select group/);
  assert.match(passengerAllocation, /Clear group/);
  assert.match(passengerAllocation, /inputRef\.current\.indeterminate/);
  assert.match(passengerAllocation, /aria-expanded=\{expanded\}/);
  assert.match(rosterGrouping, /Not provided/);
  assert.match(passengerAllocation, /useState<Set<string>>/);
  assert.match(
    passengerAllocation,
    /if \(groupByFieldKey && !fieldValuesByPassenger\) return \[\]/,
  );
  assert.match(passengerAllocation, /useDeferredValue\(search\)/);
  assert.match(passengerAllocation, /<caption className="sr-only">\{caption\}<\/caption>/);
});

test("VIP actions are hotel-scoped and visibly enforce single rooms", () => {
  assert.match(passengerAllocation, /selectedAtActiveHotel/);
  assert.match(passengerAllocation, /Mark VIP/);
  assert.match(passengerAllocation, /Remove VIP/);
  assert.match(passengerAllocation, /VIP - single room/);
  assert.match(endpoints, /vip:[\s\S]*?\/vip/);
  assert.match(api, /updateRoomingVip:[\s\S]*?is_vip: boolean/);
});

test("auto allocation exposes only the six ordered priority selectors", () => {
  assert.match(autoAllocation, /const MAX_PRIORITY_SLOTS = 6/);
  assert.match(
    workspace,
    /key=\{`\$\{activeHotel\.id\}:\$\{activeHotel\.allocation_revision\}:\$\{activeHotel\.allocation_is_current\}`\}/,
  );
  assert.match(autoAllocation, /Priority \{index \+ 1\}/);
  assert.match(autoAllocation, /chosenPrioritySet\.has\(field\.key\)/);
  assert.match(autoAllocation, /sanitizePrioritySlots\(prioritySlots, allowedByKey\)/);
  assert.match(autoAllocation, /allowedByKey\.has\(key as string\)/);
  assert.doesNotMatch(autoAllocation, /Available grouping fields/);
  assert.doesNotMatch(autoAllocation, /addPriority\(field\.key\)/);
  assert.doesNotMatch(autoAllocation, /Universal gender rule - cannot be changed/);
  assert.doesNotMatch(
    autoAllocation,
    /between the Staff or Agent\/Employee Code column/,
  );
  assert.match(priorityPolicy, /FIXED_EXPORT_FIELD_COMPACT_KEYS/);
  assert.match(priorityPolicy, /token === "gender" \|\| token === "sex"/);
  assert.match(priorityPolicy, /compact\.startsWith\("gender"\)/);
  assert.match(priorityPolicy, /compact\.endsWith\("gender"\)/);
  assert.match(priorityPolicy, /replace\(\/\(\[a-z0-9\]\)\(\[A-Z\]\)\/g/);
  assert.match(priorityPolicy, /"age_group"/);
  assert.match(priorityPolicy, /"passport_number"/);
  assert.match(priorityPolicy, /"place_of_issue"/);
  assert.match(endpoints, /priorityFields:[\s\S]*?priority-fields/);
  assert.match(endpoints, /autoAllocate:[\s\S]*?auto-allocate/);
});

test("Excel export is in the generated-plan header and not the page header", () => {
  assert.doesNotMatch(workspace, /Export Excel/);
  assert.match(workspace, /isExporting=\{isExporting\}/);
  assert.match(workspace, /onExport=\{exportHotel\}/);
  assert.match(autoAllocation, /3\. Auto-generated room plan/);
  assert.match(autoAllocation, /Export Excel/);
  assert.match(autoAllocation, /onClick=\{\(\) => void onExport\(\)\}/);
  assert.doesNotMatch(autoAllocation, /Current allocation revision/);
});

test("compact fixed and Gender aliases can never become priorities", () => {
  for (const label of [
    "PassengerGender",
    "PassengerSexField",
    "Gender Identity",
    "Sex Field",
    "PassportNumber",
    "AgeGroup",
    "GivenName",
  ]) {
    assert.equal(
      isRoomingPriorityFieldAllowed({
        key: `whatsapp:${label}`,
        label,
      }),
      false,
      `${label} must be excluded`,
    );
  }
  assert.equal(
    isRoomingPriorityFieldAllowed({
      key: "whatsapp:PassportNumber",
      label: "Room preference",
    }),
    false,
  );
  assert.equal(
    isRoomingPriorityFieldAllowed({
      key: "field:meal_preference",
      label: "Meal Preference",
    }),
    true,
  );
  assert.equal(
    isRoomingPriorityFieldAllowed({
      key: "custom:essex-county",
      label: "Essex County",
    }),
    true,
  );
});

test("gender and stale-plan safety rules block unsafe downstream actions", () => {
  assert.match(autoAllocation, /invalidGenderPassengers\.length === 0/);
  assert.match(autoAllocation, /odd same-gender remainder stays/);
  assert.match(api, /allocation_is_current: boolean/);
  assert.match(autoAllocation, /!hotel\.allocation_is_current/);
  assert.match(workspace, /Run auto allocation again before opening hotel check-in/);
  assert.match(autoAllocation, /run auto allocation again before export or check-in/);
});

test("structured backend validation details are surfaced and changed UI is ASCII-safe", () => {
  assert.match(
    errorMessage,
    /typeof error\.message === "object"[\s\S]*?"message" in error\.message/,
  );
  const changedRoomingSource = [
    workspace,
    passengerAllocation,
    autoAllocation,
    errorMessage,
    priorityPolicy,
    rosterGrouping,
  ].join("\n");
  assert.doesNotMatch(
    changedRoomingSource,
    /[\u00c2\u00e2\u2026\u2014\u00b7]/,
  );
});
