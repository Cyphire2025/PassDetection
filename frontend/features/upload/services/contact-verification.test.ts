import { describe, expect, it } from "vitest";
import { normalizeOtpPhone } from "./contact-verification";

describe("public OTP phone input", () => {
  it.each(["", "99999", "+91999999", "+91999999999", "+9199999999999", "919999999999", "99999999999", "invalid"])('rejects incomplete or implicit-country input "%s"', (phone) => {
    expect(normalizeOtpPhone(phone)).toBeNull();
  });
  it.each([["9999999999", "+919999999999"], ["+91 99999 99999", "+919999999999"], ["0091 99999 99999", "+919999999999"], ["+44 7700 900123", "+447700900123"]])('accepts complete "%s"', (phone, expected) => {
    expect(normalizeOtpPhone(phone)).toBe(expected);
  });
});
