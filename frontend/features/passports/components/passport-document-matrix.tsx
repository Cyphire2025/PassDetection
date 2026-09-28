"use client";

import { useMemo } from "react";
import { Card, CardContent } from "@/components/ui";
import { getPassportTextField as getStringField } from "@/lib/utils/passport-fields";
import type { PassportSubmission } from "@/types/passport.types";
import type { PassportDocumentImportPreview, PassportImageType } from "../api/passports.api";
import { matchPreviewFiles } from "../utils/passport-document-import";
import { DocumentCell } from "./passport-document-cell";

export function PassportDocumentMatrix({
  passports,
  preview,
  files = [],
  canEdit = false,
  revision = 0,
  onEdit,
}: {
  passports: PassportSubmission[];
  preview?: PassportDocumentImportPreview;
  files?: File[];
  canEdit?: boolean;
  revision?: number;
  onEdit?: (
    submissionId: string,
    imageType: PassportImageType,
    label: string,
    returnFocusTarget: HTMLButtonElement,
  ) => void;
}) {
  const matchedFiles = useMemo(
    () => matchPreviewFiles(preview?.accepted_documents ?? [], files),
    [files, preview?.accepted_documents],
  );
  const previewByPassenger = useMemo(() => {
    const map = new Map<
      string,
      Partial<
        Record<
          "photo" | "front" | "back",
          PassportDocumentImportPreview["accepted_documents"][number]
        >
      >
    >();
    preview?.accepted_documents.forEach((item) => {
      if (!item.passenger_id || !item.document_type) return;
      const current = map.get(item.passenger_id) ?? {};
      current[item.document_type] = item;
      map.set(item.passenger_id, current);
    });
    return map;
  }, [preview]);

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-left text-sm">
            <caption className="sr-only">
              Current passenger document assignments
            </caption>
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th scope="col" className="px-5 py-4">
                  Person
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport pic
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport front
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport back
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport front cover
                </th>
                <th scope="col" className="px-5 py-4">
                  Passport back cover
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {passports.map((passport) => {
                const previewDocs = previewByPassenger.get(passport.id);
                return (
                  <tr key={passport.id} className="align-top">
                    <td className="px-5 py-4">
                      <div className="font-semibold text-slate-900">
                        {passport.client_name}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {getPersonnelCode(passport) ||
                          "No staff or Agent/Employee code"}
                      </div>
                    </td>
                    <DocumentCell
                      label="Visa Photo"
                      url={passport.passport_photo_url}
                      file={
                        previewDocs?.photo
                          ? matchedFiles.get(previewDocs.photo)
                          : undefined
                      }
                      filename={previewDocs?.photo?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) =>
                        onEdit?.(
                          passport.id,
                          "visa_photo",
                          "Visa Photo",
                          trigger,
                        )
                      }
                    />
                    <DocumentCell
                      label="Passport front"
                      url={passport.image_url}
                      file={
                        previewDocs?.front
                          ? matchedFiles.get(previewDocs.front)
                          : undefined
                      }
                      filename={previewDocs?.front?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) =>
                        onEdit?.(
                          passport.id,
                          "passport_front",
                          "Passport front",
                          trigger,
                        )
                      }
                    />
                    <DocumentCell
                      label="Passport back"
                      url={passport.passport_back_url}
                      file={
                        previewDocs?.back
                          ? matchedFiles.get(previewDocs.back)
                          : undefined
                      }
                      filename={previewDocs?.back?.filename}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) =>
                        onEdit?.(
                          passport.id,
                          "passport_back",
                          "Passport back",
                          trigger,
                        )
                      }
                    />
                    <DocumentCell
                      label="Passport Front Cover"
                      url={passport.passport_cover_url}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) => onEdit?.(passport.id, "passport_cover", "Passport Front Cover", trigger)}
                    />
                    <DocumentCell
                      label="Passport Back Cover"
                      url={passport.passport_back_cover_url}
                      revision={revision}
                      canEdit={canEdit}
                      onEdit={(trigger) => onEdit?.(passport.id, "passport_back_cover", "Passport Back Cover", trigger)}
                    />
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export function getPersonnelCode(passport: PassportSubmission) {
  const fields = passport.confirmed_fields ?? passport.extracted_fields;
  const agentEmployeeType = getStringField(
    fields,
    "agent_employee_type",
  ).toLowerCase();
  const agentEmployeeCode = getStringField(fields, "agent_employee_code");
  if (agentEmployeeCode && agentEmployeeType === "agent")
    return `AGT_${agentEmployeeCode}`;
  if (agentEmployeeCode && agentEmployeeType === "employee")
    return `EMP_${agentEmployeeCode}`;
  if (agentEmployeeCode) return agentEmployeeCode;
  const metadataCode =
    passport.staff_metadata?.staff_code ?? passport.staff_metadata?.staffcode;
  const fieldCode = getStringField(fields, "staff_code");
  const value = metadataCode || fieldCode;
  if (!value) return "";
  const normalized = String(value).trim().toUpperCase();
  const prefixed = normalized.match(/^STF[_\-\s]+(.+)$/);
  return prefixed ? `STF_${prefixed[1]}` : `STF_${normalized}`;
}
