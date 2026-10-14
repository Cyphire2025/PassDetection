import type { ReturningDraft } from "../api/returning-draft.api";

type Checks = Pick<ReturningDraft, "extraction_status" | "ecr_status">;
export const draftChecksPending = (draft?: Checks) => [draft?.extraction_status, draft?.ecr_status].some((status) => status === "pending" || status === "running");
export const draftChecksFailed = (draft?: Checks) => [draft?.extraction_status, draft?.ecr_status].includes("failed");
