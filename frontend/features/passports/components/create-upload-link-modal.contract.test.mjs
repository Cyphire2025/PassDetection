import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const modalSource = readFileSync(
  new URL("./create-upload-link-modal.tsx", import.meta.url),
  "utf8",
);
const schemaSource = readFileSync(
  new URL("../schemas/upload-link.schema.ts", import.meta.url),
  "utf8",
);

test("link creation cannot submit twice before pending state rerenders", () => {
  assert.match(
    modalSource,
    /if \(isPending \|\| !tryEnterCreate\(\)\) return;/,
  );
  assert.match(modalSource, /if \(inFlightRef\.current\) return false;/);
  assert.match(modalSource, /inFlightRef\.current = true;/);
  assert.match(modalSource, /leaveCreate\(\);/);
});

test("an in-flight link result cannot be discarded by closing the modal", () => {
  assert.match(modalSource, /if \(isPending\) return;/);
  assert.match(modalSource, /disabled=\{isPending\}/);
  assert.match(modalSource, /aria-busy=\{isPending\}/);
});

test("link creation and clipboard failures are visible and accessible", () => {
  assert.match(
    modalSource,
    /The upload link could not be created\. Check your connection and try again\./,
  );
  assert.match(
    modalSource,
    /The link could not be copied automatically\./,
  );
  assert.match(modalSource, /role="alert"/);
});

test("whitespace-only group names are rejected", () => {
  assert.match(
    schemaSource,
    /name: z\.string\(\)\.trim\(\)\.min\(1, "Group name is required"\)/,
  );
});

test("group creation requires destination and Travel/Departure dates", () => {
  assert.match(
    schemaSource,
    /destination: z\.string\(\)\.trim\(\)\.min\(1, "Destination is required"\)/,
  );
  assert.match(schemaSource, /Travel\/Departure date is required/);
  assert.match(schemaSource, /Return date is required/);
  assert.match(schemaSource, /Return date cannot be before the Travel\/Departure date/);
  assert.match(modalSource, /label="Travel\/Departure Date"/);
  assert.equal(modalSource.match(/required/g)?.length >= 3, true);
});

test("group creation requires and submits a canonical trip timezone", () => {
  assert.match(schemaSource, /timezone: z\.string\(\)/);
  assert.match(schemaSource, /\.refine\(isSupportedIanaTimeZone/);
  assert.match(modalSource, /timezone: DEFAULT_TRIP_TIMEZONE/);
  assert.match(modalSource, /<TripTimeZoneField/);
  assert.match(modalSource, /\.\.\.register\("timezone"\)/);
});

test("group creation can link a bounded set of existing WhatsApp broadcasts", () => {
  assert.match(modalSource, /<WhatsAppBroadcastSelector/);
  assert.match(modalSource, /name: "whatsapp_broadcast_group_ids"/);
  assert.match(
    modalSource,
    /setValue\(\s*"whatsapp_broadcast_group_ids"/,
  );
  assert.match(
    schemaSource,
    /whatsapp_broadcast_group_ids: z\.array\(z\.string\(\)\.uuid\(\)\)\.max\(50\)/,
  );
});

test("group creation supports typed details and repeatable free-text headings", () => {
  assert.match(modalSource, /label="Designation"/);
  assert.match(modalSource, /label="Agency\/Dealership Name"/);
  assert.match(modalSource, /<CustomDetailBuilder/);
  assert.match(schemaSource, /custom_details: z\.array\(customDetailSchema\)\.max\(20\)/);
  assert.match(schemaSource, /Custom detail names must be unique/);
});
