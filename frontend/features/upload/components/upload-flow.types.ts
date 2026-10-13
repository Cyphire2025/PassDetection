import type { PassportSubmission } from "@/types/passport.types";
import type { CompletionResult } from "@/features/travellers/types";

export type FlowMode = "single" | "family";
export type AgentEmployeeType = "" | "agent" | "employee";
export type UploadFlowStep =
  | "BOOTSTRAP"
  | "RECOVERY_ERROR"
  | "QUALIFIER_SELECT"
  | "MODE_SELECT"
  | "FAMILY_SETUP"
  | "METHOD_SELECT"
  | "SELFIE_CAMERA"
  | "SELFIE_UPLOAD"
  | "CAMERA"
  | "PASSPORT_UPLOAD"
  | "UPLOADING"
  | "REVIEW"
  | "FAMILY_REVIEW"
  | "SUBMITTING"
  | "SUCCESS";

export interface FamilyMember {
  reuseCompletion?: { binding: FamilyReuseBinding; result: CompletionResult & { source_submission_id: string } };
  replacementAssociated?: FamilyReuseBinding;
  localId: string;
  name: string;
  relation: string;
  gender: string;
  email: string;
  phone: string;
  baseCity: string;
  nearestDomesticAirport: string;
  staffCode: string;
  agentEmployeeType: AgentEmployeeType;
  agentEmployeeCode: string;
  designation: string;
  agencyDealershipName: string;
  mealPreference: string;
  customAnswers: Record<string, string>;
  customDetailAnswers: Record<string, string>;
  submission: PassportSubmission | null;
  reviewFields: Record<string, string>;
  visaSelfie: File | null;
  visaPhotoSource: "camera" | "file" | null;
  uploadIdempotencyKey: string;
  extractionNotice: string | null;
  canRetryExtraction: boolean;
}

export interface FamilyReuseBinding { localId: string; sourceSubmissionId: string; extractionRevision: number; uploadSessionId: string }

export interface PassportDocumentBundle {
  front: File | null;
  back: File | null;
  cover: File | null;
  back_cover: File | null;
  frontSource: "camera" | "file" | null;
  backSource: "camera" | "file" | null;
  frontManuallyCropped: boolean;
  backManuallyCropped: boolean;
}

export interface ExtractionWaitResult {
  submission: PassportSubmission;
  notice: string | null;
  retryAllowed: boolean;
}
