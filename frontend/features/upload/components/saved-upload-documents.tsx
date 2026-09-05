import type { PassportSubmission } from "@/types/passport.types";
import { ProtectedUploadDocumentImage } from "./protected-upload-document-image";
import { PassportRoiOverlays } from "./upload-flow-review";

export function SavedUploadDocuments({ submission, token, uploadSessionId }: {
  submission: PassportSubmission;
  token: string;
  uploadSessionId: string;
}) {
  const documents = [
    { type: "photo", key: submission.passport_photo_s3_key, label: "Visa Photo" },
    { type: "cover", key: submission.passport_cover_s3_key, label: "Passport Front Cover" },
    { type: "back_cover", key: submission.passport_back_cover_s3_key, label: "Passport Back Cover" },
    { type: "front", key: submission.image_s3_key, label: "Personal Details Page" },
    { type: "back", key: submission.passport_back_s3_key, label: "Address Details Page" },
  ] as const;
  const savedDocuments = documents.filter((document) => Boolean(document.key));
  if (!savedDocuments.length) return <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm leading-6 text-slate-500">Your travel agency has allowed you to continue without passport images. Please complete the requested details.</p>;
  return <div className="space-y-4">{savedDocuments.map((document) => (
    <figure key={document.type} className="mx-auto w-fit max-w-full rounded-2xl border border-slate-200 bg-white p-3 shadow-sm lg:mx-0">
      <ProtectedUploadDocumentImage token={token} submissionId={submission.id} uploadSessionId={uploadSessionId} documentType={document.type} alt={`${submission.client_name || "Traveller"}: ${document.label}`} overlay={document.type === "front" ? <PassportRoiOverlays fields={submission.extracted_fields} /> : null} />
      <figcaption className="mt-2 text-center text-xs font-medium text-slate-500">{document.label}</figcaption>
    </figure>
  ))}</div>;
}
