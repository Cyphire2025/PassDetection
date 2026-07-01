"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Download, Eye, FileText, RotateCcw, Search } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import { useExportPassportGroup, usePassportsByGroup, useReextractPassportSubmission } from "../hooks/use-passports";

interface PassportGroupDetailProps {
  groupId: string;
}

export function PassportGroupDetail({ groupId }: PassportGroupDetailProps) {
  const [search, setSearch] = useState("");
  const { data, isLoading, error } = usePassportsByGroup(groupId, search);
  const reextractMutation = useReextractPassportSubmission();
  const exportMutation = useExportPassportGroup();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Group Submissions"
          description="Review the passport submissions uploaded through this group link."
        />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            className="gap-2"
            disabled={exportMutation.isPending}
            onClick={() => exportMutation.mutate(groupId)}
          >
            <Download className="h-4 w-4" />
            {exportMutation.isPending ? "Exporting" : "Export Excel"}
          </Button>
          <Link href={ROUTES.dashboard.passports}>
            <Button variant="outline" className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to Groups
            </Button>
          </Link>
        </div>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name, email, phone, passport number"
          className="h-10 pl-9"
        />
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load passport submissions for this group.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No passports in this group"
          description="Passport submissions will appear here after clients upload through this group link."
        />
      ) : (
        <>
          <div className="grid gap-4 lg:hidden">
            {data.map((passport) => (
              <PassportMobileCard key={passport.id} passport={passport} />
            ))}
          </div>

          <Card className="hidden lg:block">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                      <th className="px-6 py-4">Client</th>
                      <th className="px-6 py-4">Status</th>
                      <th className="px-6 py-4">Passport</th>
                      <th className="px-6 py-4">Confidence</th>
                      <th className="px-6 py-4">Updated</th>
                      <th className="px-6 py-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.map((passport) => (
                      <tr key={passport.id} className="hover:bg-slate-50/60">
                        <td className="px-6 py-4">
                          <div className="font-semibold text-slate-900">{passport.client_name}</div>
                          <div className="mt-1 text-xs text-slate-500">{passport.client_email ?? "No email provided"}</div>
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={passport.status} />
                        </td>
                        <td className="px-6 py-4">
                          <div className="font-medium text-slate-800">{getStringField(passport.extracted_fields, "passport_number") || "Not extracted"}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {getStringField(passport.extracted_fields, "nationality") || getStringField(passport.extracted_fields, "issuing_country") || "Manual review"}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-slate-700">{formatConfidence(passport.overall_confidence)}</td>
                        <td className="px-6 py-4 text-slate-500">{formatDateTime(passport.updated_at)}</td>
                        <td className="px-6 py-4">
                          <div className="flex items-center justify-end gap-2">
                            {needsReextraction(passport) && (
                              <Button
                                variant="secondary"
                                size="sm"
                                className="gap-2"
                                disabled={reextractMutation.isPending}
                                onClick={() => reextractMutation.mutate(passport.id)}
                              >
                                <RotateCcw className="h-4 w-4" />
                                {reextractMutation.isPending && reextractMutation.variables === passport.id ? "Retrying" : "Re-extract"}
                              </Button>
                            )}
                            <Link href={ROUTES.dashboard.passportDetail(passport.id) as never}>
                              <Button variant="outline" size="sm" className="gap-2">
                                <Eye className="h-4 w-4" />
                                Open
                              </Button>
                            </Link>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function PassportMobileCard({ passport }: { passport: PassportSubmission }) {
  const reextractMutation = useReextractPassportSubmission();

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{passport.client_name}</h3>
            <p className="mt-1 text-xs text-slate-500">{passport.client_email ?? "No email provided"}</p>
          </div>
          <StatusBadge status={passport.status} />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoPair label="Passport" value={getStringField(passport.extracted_fields, "passport_number") || "Not extracted"} />
          <InfoPair
            label="Nationality"
            value={getStringField(passport.extracted_fields, "nationality") || getStringField(passport.extracted_fields, "issuing_country") || "Manual review"}
          />
          <InfoPair label="Confidence" value={formatConfidence(passport.overall_confidence)} />
          <InfoPair label="Updated" value={formatDateTime(passport.updated_at)} />
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {needsReextraction(passport) && (
            <Button
              variant="secondary"
              className="w-full gap-2"
              disabled={reextractMutation.isPending}
              onClick={() => reextractMutation.mutate(passport.id)}
            >
              <RotateCcw className="h-4 w-4" />
              {reextractMutation.isPending ? "Retrying" : "Re-extract"}
            </Button>
          )}
          <Link href={ROUTES.dashboard.passportDetail(passport.id) as never} className="block">
            <Button variant="outline" className="w-full gap-2">
              <Eye className="h-4 w-4" />
              Open Submission
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

function needsReextraction(passport: PassportSubmission) {
  return (
    passport.status === "failed" ||
    !getStringField(passport.extracted_fields, "passport_number") ||
    (passport.overall_confidence ?? 0) <= 0.2
  );
}

function getStringField(fields: ExtractedPassportFields | null, key: string) {
  const value = fields?.[key];
  return typeof value === "string" ? value : "";
}

function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 font-medium text-slate-800">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={PASSPORT_STATUS_COLORS[status] || "default"} dot>
      {PASSPORT_STATUS_LABELS[status] || status}
    </Badge>
  );
}
