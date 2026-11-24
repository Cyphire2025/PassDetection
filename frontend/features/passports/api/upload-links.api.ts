import { uploadLinkManagementApi } from "./upload-link-management.api";
import { uploadLinkRosterApi } from "./upload-link-roster.api";
import { publicUploadLinkApi } from "./public-upload-link.api";

export type {
  CustomUploadQuestion,
  CustomUploadDetail,
  UpdateUploadLinkRequest,
  CreateUploadLinkRequest,
  WhatsAppMatchFieldOption,
  LinkedWhatsAppBroadcast,
  GroupWhatsAppLinksResponse,
  GroupWhatsAppMatchStatus,
  GroupWhatsAppMatchCounts,
  GroupWhatsAppMatchEvidence,
  GroupWhatsAppRecipientFields,
  GroupWhatsAppSubmissionDetail,
  GroupWhatsAppMatch,
  GroupWhatsAppMatchesResponse,
  GroupWhatsAppMatchesParams,
  ReplacementCandidate,
  ReplacementCandidateListResponse,
  PassportRosterResolution,
  QualifierRelationOption,
  UploadLinkResponse,
  QualifierSelectionState,
} from "./upload-link.types";

/** Private staff commands and public traveller proofs retain distinct transport owners. */
export const uploadLinksApi = {
  ...uploadLinkManagementApi,
  ...uploadLinkRosterApi,
  ...publicUploadLinkApi,
};
