import type {
  PassportSubmission,
  ExtractedPassportFields,
  PassportExtractionConflict,
  StaffApprovalResult,
} from "@/types/passport.types";
import type { StaffApprovalFeedback } from "../utils/passport-review";

export interface ReextractFeedback {
  tone: "processing" | "success" | "warning" | "error";
  message: string;
}
export interface ReviewFieldsCardProps {
  passport: PassportSubmission;
  sourceFields: ExtractedPassportFields;
  validation?: ExtractedPassportFields["field_validation"];
  conflicts: PassportExtractionConflict[];
  isSaving: boolean;
  canRetryAiVerification: boolean;
  isRetryingAiVerification: boolean;
  canReextract: boolean;
  isReextracting: boolean;
  reextractFeedback: ReextractFeedback | null;
  approvalFeedback: StaffApprovalFeedback | null;
  formError: string | null;
  onFormError: (error: string | null) => void;
  onConfirm: (fields: Record<string, string>) => Promise<unknown>;
  onStaffApprove: (
    fields: Record<string, string>,
    reviewReason?: string,
  ) => Promise<StaffApprovalResult>;
  onRetryAiVerification: () => Promise<unknown>;
  reviewerLabel: string | null;
  onReextract: () => void;
}
