import { describe, expect, it } from "vitest";
import { matchExplanation } from "./whatsapp-match-description";

describe("WhatsApp matching explanations", () => {
  it("distinguishes identified travellers sharing qualifier details from duplicates", () => {
    expect(matchExplanation({ status: "submitted", submission_ids: ["first", "second"] }))
      .toContain("Shared qualifier details alone do not make them duplicates");
    expect(matchExplanation({ status: "submitted", submission_ids: ["first"] }))
      .toBe("Automatically linked using reliable matching details.");
  });

  it("explains duplicate passport evidence instead of treating all repeated codes as duplicates", () => {
    expect(matchExplanation({ status: "multiple_submissions", submission_ids: ["first", "repeat"] }))
      .toContain("Repeated passenger passport details");
  });

  it("directs unmatched uploads to manual corrections without offering fuzzy matching", () => {
    expect(matchExplanation({ status: "unmatched_submission", submission_ids: ["first"] }))
      .toContain("correct client-provided details");
  });
});
