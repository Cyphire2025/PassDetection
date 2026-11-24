import { describe, expect, it } from "vitest";
import { speechChunks } from "./speech-text";

describe("long spoken answers", () => {
  it("keeps the end of a long answer instead of silently truncating it", () => {
    const text = "These are the verified travel details. ".repeat(260) + "The final departure is tomorrow.";
    const chunks = speechChunks(text);
    expect(chunks.length).toBeGreaterThan(3);
    expect(chunks.every((chunk) => chunk.length <= 1800)).toBe(true);
    expect(chunks.every((chunk) => new TextEncoder().encode(chunk).length <= 1700)).toBe(true);
    expect(chunks.join(" ")).toContain("The final departure is tomorrow.");
  });
  it("keeps emoji intact and removes formatting markers from speech", () => {
    const chunks = speechChunks("**Journey** " + "✈️ 🧳 ".repeat(450) + "Complete.");
    expect(chunks[0]).toMatch(/^Journey /);
    expect(chunks.every((chunk) => !/[\ud800-\udbff]$/.test(chunk))).toBe(true);
    expect(chunks.at(-1)).toMatch(/Complete\.$/);
  });
});
