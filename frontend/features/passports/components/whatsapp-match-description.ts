import type { GroupWhatsAppMatch } from "../api/upload-links.api";

export function matchExplanation(row: Pick<GroupWhatsAppMatch, "status" | "submission_ids">): string {
  if (row.status === "submitted") {
    return row.submission_ids.length > 1
      ? "Several travellers are identified under this recipient using matching details. Shared qualifier details alone do not make them duplicates."
      : "Automatically linked using reliable matching details.";
  }
  if (row.status === "multiple_submissions") {
    return "Repeated passenger passport details were found. Duplicate badges mark the affected uploads; a shared producer code alone is not a duplicate.";
  }
  if (row.status === "needs_review") {
    return "Some details match, but competing or uncertain evidence needs staff review. Matching uploads have been kept here, not discarded as unidentified.";
  }
  if (row.status === "unmatched_submission") {
    return "No reliable match was found in the selected broadcasts. Open the submission to check and correct client-provided details.";
  }
  if (row.status === "replacement") {
    return "This person is going in place of the selected original broadcast recipient.";
  }
  if (row.status === "rejected_upload") {
    return "This unidentified upload was removed from the active list without deleting its saved details.";
  }
  return "No submission could be linked reliably to this broadcast recipient.";
}
