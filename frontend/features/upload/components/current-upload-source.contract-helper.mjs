import { readFileSync } from "node:fs";
export const readUploadSource = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
export const currentUploadSources = Object.freeze({
  portal: readUploadSource("./traveller-portal.tsx"),
  fresh: readUploadSource("./fresh-flow.tsx"),
  form: readUploadSource("./fresh-member-form.tsx"),
  draft: readUploadSource("../hooks/use-fresh-draft.ts"),
  contact: readUploadSource("../hooks/use-fresh-contact.ts"),
  submission: readUploadSource("../hooks/use-fresh-member-submission.ts"),
  selection: readUploadSource("../hooks/use-selected-document-uploads.ts"),
  documents: readUploadSource("./fresh-documents.tsx"),
  validation: readUploadSource("../services/fresh-validation.ts"),
  documentValidation: readUploadSource("../services/fresh-document-validation.ts"),
  api: readUploadSource("../api/fresh-draft.api.ts"),
  initialization: readUploadSource("../../travellers/hooks/use-draft-initialization.ts"),
  returning: readUploadSource("../../travellers/hooks/use-returning-draft.ts"),
  resume: readUploadSource("../../travellers/services/draft-resume.ts"),
});
