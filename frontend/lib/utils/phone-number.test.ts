import { describe, expect, it } from "vitest";
import { normalizePhoneNumber } from "./phone-number";

describe("traveller phone format shared with WhatsApp", () => {
  it.each([
    ["9876543210", "+919876543210"], ["(987) 654-3210", "+919876543210"],
    ["+44 7700 900123", "+447700900123"], ["0044 7700 900123", "+447700900123"],
    ["919876543210", "+919876543210"], ["1234567", null], ["12345678", null],
    ["+01234567890", null], ["123+4567890", null], ["9876543210 ext 2", null],
    ["+1234567890123456", null], ["९८७६५४३२१०", null], ["", null], [null, null],
  ])("normalizes %s to %s", (raw, expected) => expect(normalizePhoneNumber(raw)).toBe(expected));
});
