import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (name) => readFileSync(new URL(name, import.meta.url), "utf8");

const sharedUi = read("./operations-workspace-ui.tsx");
const tourAssignments = read("./tour-group-assignments-page.tsx");
const tourUi = read("./tour-operations-ui.tsx");
const attendance = read("./tour-group-attendance-page.tsx");
const qrCodes = read("./tour-group-qr-codes-page.tsx");
const roomingGroups = read("./rooming-groups-page.tsx");
const roomingWorkspace = read("./rooming-workspace-page.tsx");
const roomingPassengers = read("./rooming-passenger-hotel-allocation.tsx");
const roomingPlan = read("./rooming-auto-allocation.tsx");
const checkin = read("./hotel-checkin-dashboard.tsx");

test("operations pages use a compact contextual header and summary system", () => {
  assert.match(sharedUi, /export function OperationsPageHeader/);
  assert.match(sharedUi, /export function OperationsSummaryStrip/);
  assert.match(sharedUi, /aria-label=\{label\}/);
  assert.match(tourAssignments, /eyebrow="Live field operations"/);
  assert.match(roomingGroups, /eyebrow="Hotel planning workspace"/);
  assert.match(roomingWorkspace, /eyebrow="Rooming group workspace"/);
});

test("Tour Ops integrates search, coverage filters, and row-local mutation feedback", () => {
  assert.match(tourAssignments, /useDeferredValue\(query\)/);
  assert.match(tourAssignments, /Search group, destination, date, or coordinator/);
  assert.match(tourAssignments, /Needs coverage/);
  assert.match(tourAssignments, /assignGroup\.variables\?\.groupId === group\.id/);
  assert.match(tourAssignments, /Coordinator coverage/);
  assert.match(tourAssignments, /Attendance/);
  assert.match(tourAssignments, /QR codes/);
});

test("closed coordinator menus install no document listeners and expose menu state", () => {
  assert.match(tourUi, /useCloseOnOutsideClick\(open/);
  assert.match(tourUi, /if \(!enabled\) return/);
  assert.match(tourUi, /aria-expanded=\{open\}/);
  assert.match(tourUi, /role="menuitemcheckbox"/);
  assert.match(tourUi, /event\.key !== "Escape"/);
});

test("Rooming preserves the three-stage workflow while deferring check-in code", () => {
  assert.match(roomingWorkspace, /dynamic\(/);
  assert.match(roomingWorkspace, /import\("\.\/hotel-checkin-dashboard"\)/);
  assert.match(roomingPassengers, /1\. Choose who stays at each hotel/);
  assert.match(roomingPlan, /2\. Set auto-allocation priorities/);
  assert.match(roomingPlan, /3\. Auto-generated room plan/);
  assert.match(roomingWorkspace, /Check-in needs a current room plan/);
});

test("large Rooming lists avoid rerendering unchanged rows and skip offscreen paint", () => {
  assert.match(roomingPassengers, /const passengersById = useMemo/);
  assert.match(roomingPassengers, /const togglePassenger = useCallback/);
  assert.match(roomingPassengers, /const PassengerRow = memo/);
  assert.match(roomingPlan, /const ReadOnlyRoomCard = memo/);
  assert.match(roomingPlan, /content-visibility:auto/);
});

test("attendance and check-in expose semantic progress, search, and recoverable empty states", () => {
  assert.match(attendance, /role="progressbar"/);
  assert.match(attendance, /aria-valuenow=\{progress\}/);
  assert.match(attendance, /role="dialog"/);
  assert.match(attendance, /aria-modal="true"/);
  assert.match(checkin, /Search hotel check-in roster/);
  assert.match(checkin, /<caption className="sr-only">/);
  assert.match(checkin, /scope="col"/);
  assert.match(checkin, /Reset filters/);
});

test("QR distribution incrementally renders large rosters without changing print coverage", () => {
  assert.match(qrCodes, /const INITIAL_QR_CARD_LIMIT = 48/);
  assert.match(qrCodes, /filteredPassengers\.slice\(0, renderLimit\)/);
  assert.match(qrCodes, /printRequested[\s\S]*?data\?\.passengers/);
  assert.match(qrCodes, /payloadScopeIds/);
  assert.match(qrCodes, /Print all/);
  assert.match(qrCodes, /Show next/);
  assert.match(qrCodes, /content-visibility:auto/);
  assert.match(qrCodes, /Search passenger QR cards/);
});
