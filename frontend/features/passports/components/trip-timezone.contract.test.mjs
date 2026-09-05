import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const apiSource = readFileSync(
  new URL("../api/upload-links.api.ts", import.meta.url),
  "utf8",
);
import { passportGroupDetailSource as detailSource } from "./passport-group-detail-source.contract-helper.mjs";
const dialogSource = readFileSync(
  new URL("./passport-trip-details-dialog.tsx", import.meta.url),
  "utf8",
);
const fieldSource = readFileSync(
  new URL("./trip-timezone-field.tsx", import.meta.url),
  "utf8",
);
const policySource = readFileSync(
  new URL("../utils/trip-timezone.ts", import.meta.url),
  "utf8",
);

test("trip timezone is round-tripped by create, response, and edit contracts", () => {
  assert.equal((apiSource.match(/timezone[?]?: string/g) ?? []).length >= 3, true);
  assert.match(detailSource, /timezone:\s*groupDetails\.timezone \?\? DEFAULT_TRIP_TIMEZONE/);
  assert.match(detailSource, /timezone: tripForm\.timezone\.trim\(\)/);
  assert.match(detailSource, /label="Trip Timezone"/);
  assert.match(dialogSource, /<TripTimeZoneField/);
  assert.match(dialogSource, /Boolean\(timezoneError\)/);
});

test("timezone selector supports the full runtime IANA set with a stable default", () => {
  assert.match(policySource, /DEFAULT_TRIP_TIMEZONE = "Asia\/Kolkata"/);
  assert.match(policySource, /Intl\.DateTimeFormat\("en", \{ timeZone: normalized \}\)/);
  assert.match(policySource, /Intl\.supportedValuesOf\("timeZone"\)/);
  assert.match(fieldSource, /list=\{optionsId\}/);
  assert.match(fieldSource, /Controls mobile countdowns and trip-local schedule times/);
});
