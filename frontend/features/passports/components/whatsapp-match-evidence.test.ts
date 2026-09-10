import { expect, it } from "vitest";
import { groupWhatsAppEvidenceLabel } from "./whatsapp-match-evidence";

type MatchRow = Parameters<typeof groupWhatsAppEvidenceLabel>[1];

function matchRow(fields: Record<string, unknown>): MatchRow {
  return {
    submission_details: [{ fields }],
  } as MatchRow;
}

it("uses the public custom-field label associated with dynamic evidence", () => {
  expect(groupWhatsAppEvidenceLabel(
    "agent_employee_code",
    matchRow({ agent_employee_code_label: "Producer Code" }),
  )).toBe("Producer Code");
});

it("resolves a configured-label alias and safely humanizes unknown evidence", () => {
  expect(groupWhatsAppEvidenceLabel(
    "producer_code",
    matchRow({ custom_answer_0_label: "Producer Code" }),
  )).toBe("Producer Code");
  expect(groupWhatsAppEvidenceLabel(
    "regional_office",
    matchRow({}),
  )).toBe("Regional Office");
});
