import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { readDocumentWorkspaceSource } from "./document-workspace-source.contract-helper.mjs";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

const routes = read("../../../constants/routes.ts");
const landing = read("./document-distribution-landing.tsx");
const groupList = read("./document-group-list.tsx");
const workspace = readDocumentWorkspaceSource();
const uploadPanel = read("./document-upload-panel.tsx");
const navigation = read("./flight-ticket-lane-navigation.tsx");
const lanes = read("../config/document-distribution-lanes.ts");
const types = read("../../../types/document-distribution.types.ts");
const legacyDistributionPage = read(
  "../../../app/(dashboard)/documents/distribution/[groupId]/page.tsx",
);
const legacyGroupPage = read("../../../app/(dashboard)/documents/[groupId]/page.tsx");
const groupChooser = read("./document-group-distribution-chooser.tsx");
const flightDefaultPage = read(
  "../../../app/(dashboard)/documents/distribution/flight-tickets/[groupId]/page.tsx",
);
const flightLanePage = read(
  "../../../app/(dashboard)/documents/distribution/flight-tickets/[groupId]/[scope]/[leg]/page.tsx",
);
const visaPage = read(
  "../../../app/(dashboard)/documents/distribution/visa/[groupId]/page.tsx",
);

test("distribution landing exposes only the two requested document families", () => {
  assert.match(landing, /title: "Visa"/);
  assert.match(landing, /title: "Flight Tickets"/);
  assert.match(landing, /DISTRIBUTION_CATEGORIES\.map/);
  assert.doesNotMatch(landing, /useDocumentGroups/);
  assert.doesNotMatch(landing, /Departure Ticket/);
  assert.doesNotMatch(landing, /Arrival Ticket/);
});

test("category group lists preserve server-backed passenger search and route to their own workspaces", () => {
  assert.match(groupList, /category: DocumentDistributionCategory/);
  assert.match(groupList, /useDocumentGroupSearch/);
  assert.match(groupList, /Search by group, destination, or passenger/);
  assert.match(groupList, /documentDistributionVisaGroup/);
  assert.match(groupList, /documentDistributionFlightGroup/);
});

test("flight routes default safely and validate scope and leg before selecting a lane", () => {
  assert.match(routes, /documentDistributionFlightLane/);
  assert.match(flightDefaultPage, /"international"/);
  assert.match(flightDefaultPage, /"onward"/);
  assert.match(flightDefaultPage, /redirect\(/);
  assert.match(flightLanePage, /isFlightTicketScope\(scope\)/);
  assert.match(flightLanePage, /isFlightTicketLeg\(leg\)/);
  assert.match(flightLanePage, /notFound\(\)/);
  assert.match(flightLanePage, /getFlightDistributionLane\(scope, leg\)/);
});

test("legacy group URLs preserve group context with a family chooser", () => {
  assert.match(legacyDistributionPage, /DocumentGroupDistributionChooser/);
  assert.match(legacyGroupPage, /documentGroup\(groupId\)/);
  assert.match(groupChooser, /documentDistributionVisaGroup\(groupId\)/);
  assert.match(groupChooser, /documentDistributionFlightGroup\(groupId\)/);
  assert.match(visaPage, /VISA_DISTRIBUTION_LANE/);
});

test("lane registry preserves legacy international types and adds empty domestic types", () => {
  assert.match(lanes, /documentType: "flight_ticket"/);
  assert.match(lanes, /documentType: "flight_ticket_arrival"/);
  assert.match(lanes, /documentType: "flight_ticket_domestic"/);
  assert.match(lanes, /documentType: "flight_ticket_domestic_arrival"/);
  assert.match(lanes, /title: "International Onward"/);
  assert.match(lanes, /title: "International Return"/);
  assert.match(lanes, /title: "Domestic Onward"/);
  assert.match(lanes, /title: "Domestic Return"/);
  assert.match(types, /\| "flight_ticket_domestic"/);
  assert.match(types, /\| "flight_ticket_domestic_arrival"/);
});

test("workspace is immutable per route lane and flight navigation is operation-safe", () => {
  assert.match(workspace, /lane: DocumentDistributionLane/);
  assert.match(workspace, /const documentType = lane\.documentType/);
  assert.doesNotMatch(workspace, /setSelectedType/);
  assert.match(navigation, /International/);
  assert.match(navigation, /Domestic/);
  assert.match(navigation, /Onward/);
  assert.match(navigation, /Return/);
  assert.match(navigation, /aria-disabled=\{operationPending\}/);
  assert.match(navigation, /event\.preventDefault\(\)/);
  assert.match(workspace, /hasUncommittedSelection/);
  assert.match(navigation, /hasUncommittedSelection/);
  assert.match(navigation, /window\.confirm/);
  assert.match(uploadPanel, /combined Onward-and-Return PDF/);
});
