"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, CalendarDays, Download, Eye, FileText, Pencil, RotateCcw, Search, UploadCloud, X } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PASSPORT_STATUS_COLORS, PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import { useUpdateUploadLink, useUploadLinks } from "../hooks/use-upload-links";
import {
  useExportPassportGroup,
  useExportSelectedPassports,
  useImportPassportGroup,
  usePassportGroups,
  usePassportsByGroup,
  useReextractPassportSubmission,
  usePreviewPassportDocuments,
  useSavePassportDocuments,
} from "../hooks/use-passports";
import type { PassportDocumentImportPreview } from "../api/passports.api";

interface PassportGroupDetailProps {
  groupId: string;
}

export function PassportGroupDetail({ groupId }: PassportGroupDetailProps) {
  const searchParams = useSearchParams();
  const includeDeleted = searchParams.get("old_data") === "1";
  const [search, setSearch] = useState("");
  const [selectedPassports, setSelectedPassports] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [qualityFilter, setQualityFilter] = useState("all");
  const [metadataField, setMetadataField] = useState("all");
  const [metadataValue, setMetadataValue] = useState("all");
  const [sortBy, setSortBy] = useState("name");
  const [viewMode, setViewMode] = useState<"table" | "docs">("table");
  const { data, isLoading, error } = usePassportsByGroup(groupId, search, includeDeleted);
  const { data: groups = [] } = usePassportGroups();
  const { data: deletedGroups = [] } = useUploadLinks("deleted", includeDeleted);
  const deletedGroup = deletedGroups.find((item) => item.id === groupId);
  const group = groups.find((item) => item.group_id === groupId);
  const groupDetails = group ?? (deletedGroup ? {
    group_id: deletedGroup.id,
    group_name: deletedGroup.name,
    group_status: deletedGroup.status,
    total_passports: deletedGroup.deleted_passport_count,
    pending_review_count: 0,
    confirmed_count: 0,
    failed_count: 0,
    latest_submission_at: deletedGroup.deleted_at ?? deletedGroup.created_at,
    destination: deletedGroup.destination,
    travel_date: deletedGroup.travel_date,
    return_date: deletedGroup.return_date,
    package_name: deletedGroup.package_name,
    departure_cities: deletedGroup.departure_cities ?? [],
    notes: deletedGroup.notes,
  } : undefined);
  const reextractMutation = useReextractPassportSubmission();
  const exportMutation = useExportPassportGroup();
  const importMutation = useImportPassportGroup(groupId);
  const passportPreviewMutation = usePreviewPassportDocuments(groupId);
  const passportSaveMutation = useSavePassportDocuments(groupId);
  const exportSelected = useExportSelectedPassports();
  const updateGroup = useUpdateUploadLink();
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const passportImportInputRef = useRef<HTMLInputElement | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [passportImportFiles, setPassportImportFiles] = useState<File[]>([]);
  const [passportImportPreview, setPassportImportPreview] = useState<PassportDocumentImportPreview | null>(null);
  const [passportImportProgress, setPassportImportProgress] = useState<{ processed: number; total: number; label: string } | null>(null);
  const [isEditingTrip, setIsEditingTrip] = useState(false);
  const [tripForm, setTripForm] = useState({
    name: "",
    destination: "",
    travel_date: "",
    return_date: "",
    departure_cities: [] as string[],
    notes: "",
  });

  const expiryAlerts = useMemo(() => {
    return (data ?? []).filter((passport) => getExpiryStatus(passport) !== "valid");
  }, [data]);

  const metadataFields = useMemo(() => {
    const keys = new Set<string>();
    (data ?? []).forEach((passport) => Object.keys(passport.staff_metadata ?? {}).forEach((key) => {
      if (key !== "source_sheet") keys.add(key);
    }));
    return [...keys].sort();
  }, [data]);

  const metadataValues = useMemo(() => {
    if (metadataField === "all") return [];
    return [...new Set((data ?? []).map((passport) => passport.staff_metadata?.[metadataField]).filter(Boolean) as string[])].sort();
  }, [data, metadataField]);

  const filteredPassports = useMemo(() => {
    return (data ?? []).filter((passport) => {
      if (statusFilter !== "all" && passport.status !== statusFilter) return false;
      const confidence = passport.overall_confidence ?? 0;
      if (qualityFilter === "low_confidence" && confidence > 0.5) return false;
      if (qualityFilter === "missing_passport" && getStringField(passport.extracted_fields, "passport_number")) return false;
      if (qualityFilter === "expiry_alert" && getExpiryStatus(passport) === "valid") return false;
      if (qualityFilter === "complete" && needsReextraction(passport)) return false;
      if (metadataField !== "all" && metadataValue !== "all" && passport.staff_metadata?.[metadataField] !== metadataValue) return false;
      return true;
    }).sort((left, right) => {
      const leftValue = sortBy === "name" ? left.client_name : (left.staff_metadata?.[sortBy] ?? "");
      const rightValue = sortBy === "name" ? right.client_name : (right.staff_metadata?.[sortBy] ?? "");
      return leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
    });
  }, [data, metadataField, metadataValue, qualityFilter, sortBy, statusFilter]);

  const togglePassport = (passportId: string) => {
    setSelectedPassports((current) =>
      current.includes(passportId) ? current.filter((id) => id !== passportId) : [...current, passportId],
    );
  };

  const handlePassportImportFiles = async (files: File[]) => {
    setImportMessage(null);
    setPassportImportPreview(null);
    const containsZip = files.some((file) => file.name.toLowerCase().endsWith(".zip"));
    if (containsZip) {
      setPassportImportFiles(files);
      setPassportImportProgress({ processed: 0, total: files.length, label: "Uploading archive for document check" });
      passportPreviewMutation.mutate({
        files,
        onProgress: (progress) => {
          setPassportImportProgress({
            processed: progress.loaded,
            total: progress.total,
            label: progress.phase === "uploading" ? "Uploading archive for document check" : "Checking documents",
          });
        },
      }, {
        onSuccess: (preview) => {
          setPassportImportPreview(preview);
          setPassportImportProgress(null);
        },
        onError: (error) => {
          setPassportImportProgress(null);
          setImportMessage(error instanceof Error ? error.message : "Passport document check failed");
        },
      });
      return;
    }

    setPassportImportProgress({ processed: 0, total: files.length, label: "Checking document names" });
    const preview = await buildLocalPassportDocumentPreview(groupId, files, data ?? [], (processed, total) => {
      setPassportImportProgress({ processed, total, label: "Checking document names" });
    });
    const acceptedNames = new Set(preview.accepted_documents.map((item) => item.filename));
    setPassportImportFiles(files.filter((file) => acceptedNames.has(file.name)));
    setPassportImportPreview(preview);
    setPassportImportProgress(null);
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Group Submissions"
          description="Review the passport submissions uploaded through this group link."
        />
        <div className="flex flex-wrap gap-2">
          <input
            ref={importInputRef}
            type="file"
            accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              setImportMessage(null);
              importMutation.mutate(file, {
                onSuccess: (result) => {
                  setSelectedPassports([]);
                  setImportMessage(
                    `Imported ${result.imported_count} new, updated ${result.updated_count}, skipped ${result.skipped_count} duplicate row${result.skipped_count === 1 ? "" : "s"}.`,
                  );
                },
                onError: (error) => {
                  const message = error instanceof Error ? error.message : "Import failed";
                  setImportMessage(message);
                },
              });
            }}
          />
          <input
            ref={passportImportInputRef}
            type="file"
            multiple
            accept=".zip,image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (!files.length) return;
              void handlePassportImportFiles(files);
            }}
          />
          <Button
            variant="secondary"
            className="gap-2"
            disabled={importMutation.isPending}
            onClick={() => importInputRef.current?.click()}
          >
            <UploadCloud className="h-4 w-4" />
            {importMutation.isPending ? "Importing" : "Import Excel"}
          </Button>
          <Button
            variant="secondary"
            className="gap-2"
            disabled={passportPreviewMutation.isPending || passportSaveMutation.isPending}
            onClick={() => passportImportInputRef.current?.click()}
          >
            <UploadCloud className="h-4 w-4" />
            {passportPreviewMutation.isPending ? "Checking documents" : "Import Passports"}
          </Button>
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

      {groupDetails && (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                  <CalendarDays className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Destination / Trip Details</h2>
                  <p className="text-sm text-slate-500">Used for search, filters, and exports.</p>
                </div>
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  setTripForm({
                    name: groupDetails.group_name,
                    destination: groupDetails.destination ?? "",
                    travel_date: groupDetails.travel_date ?? "",
                    return_date: groupDetails.return_date ?? "",
                    departure_cities: groupDetails.departure_cities ?? [],
                    notes: groupDetails.notes ?? "",
                  });
                  setIsEditingTrip(true);
                }}
              >
                <Pencil className="h-4 w-4" />
                Edit
              </Button>
            </div>
            <div className="grid gap-3 text-sm sm:grid-cols-3">
              <InfoPair label="Destination" value={groupDetails.destination || "Not set"} />
              <InfoPair label="Travel Date" value={groupDetails.travel_date || "Not set"} />
              <InfoPair label="Return Date" value={groupDetails.return_date || "Not set"} />
              <InfoPair label="Departure Cities" value={(groupDetails.departure_cities ?? []).join(", ") || "Not set"} />
              <div className="sm:col-span-2">
                <InfoPair label="Notes" value={groupDetails.notes || "No notes"} />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {importMessage && (
        <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          {importMessage}
        </div>
      )}

      {passportImportProgress && (
        <PassportDocumentImportProgress
          processed={passportImportProgress.processed}
          total={passportImportProgress.total}
          label={passportImportProgress.label}
        />
      )}

      {passportImportPreview && (
        <PassportDocumentImportDialog
          preview={passportImportPreview}
          passports={data ?? []}
          saving={passportSaveMutation.isPending}
          onClose={() => {
            if (!passportSaveMutation.isPending) setPassportImportPreview(null);
          }}
          onSave={() => {
            passportSaveMutation.mutate({
              files: passportImportFiles,
              onProgress: (progress) => {
                setPassportImportProgress({
                  processed: progress.loaded,
                  total: progress.total,
                  label: progress.phase === "uploading" ? "Uploading accepted documents" : "Saving accepted documents",
                });
              },
            }, {
              onSuccess: (result) => {
                setImportMessage(`Saved ${result.saved_count} passport document${result.saved_count === 1 ? "" : "s"}. Rejected files were not stored.`);
                setPassportImportPreview(null);
                setPassportImportFiles([]);
                setPassportImportProgress(null);
              },
              onError: (error) => {
                setPassportImportProgress(null);
                setImportMessage(error instanceof Error ? error.message : "Could not save passport documents");
              },
            });
          }}
        />
      )}

      {expiryAlerts.length > 0 && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <AlertTriangle className="h-5 w-5 text-red-700" />
                <div>
                  <h2 className="text-base font-semibold text-red-950">Passport Expiry Alerts</h2>
                  <p className="text-sm text-red-800">Passports expired or expiring within 6 months.</p>
                </div>
              </div>
              <Badge variant="destructive">{expiryAlerts.length}</Badge>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {expiryAlerts.map((passport) => (
                <Link
                  key={passport.id}
                  href={ROUTES.dashboard.passportDetail(passport.id) as never}
                  className="rounded-lg border border-red-200 bg-white p-3 hover:bg-red-50"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-900">{passport.client_name}</div>
                      <div className="text-xs text-slate-500">
                        {getStringField(passport.extracted_fields, "passport_number") || "Passport number not extracted"}
                      </div>
                    </div>
                    <div className="text-right text-sm font-medium text-red-800">
                      {getStringField(passport.extracted_fields, "date_of_expiry") || "Expiry missing"}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name, email, phone, passport number"
          className="h-10 pl-9"
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All statuses</option>
          <option value="client_submitted">Client submitted</option>
          <option value="confirmed">Confirmed</option>
          <option value="review_required">Review required</option>
          <option value="failed">Failed</option>
        </select>
        {metadataFields.length > 0 && (
          <>
            <select
              value={metadataField}
              onChange={(event) => { setMetadataField(event.target.value); setMetadataValue("all"); }}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            >
              <option value="all">All staff fields</option>
              {metadataFields.map((field) => <option key={field} value={field}>{formatMetadataLabel(field)}</option>)}
            </select>
            {metadataField !== "all" && (
              <select
                value={metadataValue}
                onChange={(event) => setMetadataValue(event.target.value)}
                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                <option value="all">All {formatMetadataLabel(metadataField)}</option>
                {metadataValues.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            )}
            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value)}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            >
              <option value="name">Sort: name</option>
              {metadataFields.map((field) => <option key={field} value={field}>Sort: {formatMetadataLabel(field)}</option>)}
            </select>
          </>
        )}
        <select
          value={qualityFilter}
          onChange={(event) => setQualityFilter(event.target.value)}
          className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All quality</option>
          <option value="low_confidence">Low confidence</option>
          <option value="missing_passport">Missing passport number</option>
          <option value="expiry_alert">Expired / expiring soon</option>
          <option value="complete">Complete</option>
        </select>
        <Button
          type="button"
          variant="secondary"
          disabled={selectedPassports.length === 0}
          isLoading={exportSelected.isPending}
          onClick={() => exportSelected.mutate(selectedPassports)}
        >
          <Download className="h-4 w-4" />
          Export Selected ({selectedPassports.length})
        </Button>
        {selectedPassports.length > 0 && (
          <Button type="button" variant="ghost" onClick={() => setSelectedPassports([])}>
            Clear selection
          </Button>
        )}
        <Button
          type="button"
          variant={viewMode === "docs" ? "primary" : "secondary"}
          onClick={() => setViewMode((current) => current === "docs" ? "table" : "docs")}
        >
          {viewMode === "docs" ? "Table view" : "DOCS view"}
        </Button>
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
          icon={<UploadCloud className="h-5 w-5" />}
          title="Drop passport here"
          description="Share this group link with clients or upload a passport through the client page. Submitted passports will appear here."
        />
      ) : filteredPassports.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No passports match these filters"
          description="Adjust search, status, or quality filters to find more submissions."
          action={{ label: "Reset Filters", onClick: () => { setSearch(""); setStatusFilter("all"); setQualityFilter("all"); setMetadataField("all"); setMetadataValue("all"); setSortBy("name"); } }}
        />
      ) : viewMode === "docs" ? (
        <PassportDocumentMatrix passports={filteredPassports} />
      ) : (
        <>
          <div className="grid gap-4 lg:hidden">
            {filteredPassports.map((passport) => (
              <PassportMobileCard
                key={passport.id}
                passport={passport}
                selected={selectedPassports.includes(passport.id)}
                onToggle={() => togglePassport(passport.id)}
              />
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
                    {filteredPassports.map((passport) => (
                      <tr
                        key={passport.id}
                        className="cursor-pointer hover:bg-slate-50/60"
                        onClick={() => togglePassport(passport.id)}
                      >
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={selectedPassports.includes(passport.id)}
                              onChange={() => togglePassport(passport.id)}
                              onClick={(event) => event.stopPropagation()}
                              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            />
                            <div>
                              <div className="font-semibold text-slate-900">{passport.client_name}</div>
                              <div className="mt-1 text-xs text-slate-500">{passport.client_email ?? "No email provided"}</div>
                            </div>
                          </div>
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
                                onClick={(event) => {
                                  event.stopPropagation();
                                  reextractMutation.mutate(passport.id);
                                }}
                              >
                                <RotateCcw className="h-4 w-4" />
                                {reextractMutation.isPending && reextractMutation.variables === passport.id ? "Retrying" : "Re-extract"}
                              </Button>
                            )}
                            <Link href={ROUTES.dashboard.passportDetail(passport.id) as never} onClick={(event) => event.stopPropagation()}>
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

      {isEditingTrip && groupDetails && (
        <TripDetailsDialog
          form={tripForm}
          isLoading={updateGroup.isPending}
          onChange={setTripForm}
          onClose={() => setIsEditingTrip(false)}
          onSave={() => {
            updateGroup.mutate(
              {
                id: groupId,
                name: tripForm.name.trim() || groupDetails.group_name,
                destination: tripForm.destination || null,
                travel_date: tripForm.travel_date || null,
                return_date: tripForm.return_date || null,
                departure_cities: normalizeCities(tripForm.departure_cities),
                notes: tripForm.notes || null,
              },
              { onSuccess: () => setIsEditingTrip(false) },
            );
          }}
        />
      )}
    </div>
  );
}

function PassportMobileCard({
  passport,
  selected,
  onToggle,
}: {
  passport: PassportSubmission;
  selected: boolean;
  onToggle: () => void;
}) {
  const reextractMutation = useReextractPassportSubmission();

  return (
    <Card className={selected ? "rounded-2xl border-blue-300 bg-blue-50/40" : "rounded-2xl"} onClick={onToggle}>
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex gap-3">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              onClick={(event) => event.stopPropagation()}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <div>
              <h3 className="text-base font-semibold text-slate-900">{passport.client_name}</h3>
              <p className="mt-1 text-xs text-slate-500">{passport.client_email ?? "No email provided"}</p>
            </div>
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
              onClick={(event) => {
                event.stopPropagation();
                reextractMutation.mutate(passport.id);
              }}
            >
              <RotateCcw className="h-4 w-4" />
              {reextractMutation.isPending ? "Retrying" : "Re-extract"}
            </Button>
          )}
          <Link href={ROUTES.dashboard.passportDetail(passport.id) as never} className="block" onClick={(event) => event.stopPropagation()}>
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

function PassportDocumentMatrix({
  passports,
  preview,
}: {
  passports: PassportSubmission[];
  preview?: PassportDocumentImportPreview;
}) {
  const previewByPassenger = useMemo(() => {
    const map = new Map<string, Partial<Record<"photo" | "front" | "back", PassportDocumentImportPreview["accepted_documents"][number]>>>();
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
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th className="px-5 py-4">Person</th>
                <th className="px-5 py-4">Passport pic</th>
                <th className="px-5 py-4">Passport front</th>
                <th className="px-5 py-4">Passport back</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {passports.map((passport) => {
                const previewDocs = previewByPassenger.get(passport.id);
                return (
                  <tr key={passport.id} className="align-top">
                    <td className="px-5 py-4">
                      <div className="font-semibold text-slate-900">{passport.client_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{getStaffCode(passport) || "No staff code"}</div>
                    </td>
                    <DocumentCell
                      label="Passport pic"
                      url={previewDocs?.photo ? undefined : passport.passport_photo_url}
                      filename={previewDocs?.photo?.filename}
                      hasDocument={Boolean(previewDocs?.photo || passport.passport_photo_s3_key)}
                    />
                    <DocumentCell
                      label="Passport front"
                      url={previewDocs?.front ? undefined : passport.image_url}
                      filename={previewDocs?.front?.filename}
                      hasDocument={Boolean(previewDocs?.front || hasRealPassportFront(passport))}
                    />
                    <DocumentCell
                      label="Passport back"
                      url={previewDocs?.back ? undefined : passport.passport_back_url}
                      filename={previewDocs?.back?.filename}
                      hasDocument={Boolean(previewDocs?.back || passport.passport_back_s3_key)}
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

function DocumentCell({
  label,
  url,
  filename,
  hasDocument,
}: {
  label: string;
  url?: string | null;
  filename?: string | null;
  hasDocument: boolean;
}) {
  return (
    <td className="px-5 py-4">
      {hasDocument ? (
        <div className="space-y-2">
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={label} className="h-24 w-36 rounded-lg border border-slate-200 object-cover" />
          ) : (
            <div className="flex h-24 w-36 items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 text-xs font-medium text-emerald-800">
              Accepted
            </div>
          )}
          <div className="max-w-44 truncate text-xs text-slate-500">{filename ?? "Saved document"}</div>
        </div>
      ) : (
        <div className="flex h-24 w-36 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-xs font-medium text-slate-400">
          No document
        </div>
      )}
    </td>
  );
}

function needsReextraction(passport: PassportSubmission) {
  if (!hasRealPassportFront(passport)) return false;
  return (
    passport.status === "failed" ||
    !getStringField(passport.extracted_fields, "passport_number") ||
    (passport.overall_confidence ?? 0) <= 0.2
  );
}

function hasRealPassportFront(passport: PassportSubmission) {
  return Boolean(passport.image_s3_key && !passport.image_s3_key.startsWith("excel-imports/"));
}

function getExpiryStatus(passport: PassportSubmission): "expired" | "near_expiry" | "valid" {
  const fields = passport.confirmed_fields ?? passport.extracted_fields;
  const rawExpiry = getStringField(fields, "date_of_expiry");
  if (!rawExpiry) return "valid";

  const expiry = new Date(`${rawExpiry}T00:00:00`);
  if (Number.isNaN(expiry.getTime())) return "valid";

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const warningDate = new Date(today);
  warningDate.setMonth(warningDate.getMonth() + 6);

  if (expiry < today) return "expired";
  if (expiry <= warningDate) return "near_expiry";
  return "valid";
}

function getStringField(fields: ExtractedPassportFields | null, key: string) {
  const value = fields?.[key];
  return typeof value === "string" ? value : "";
}

const PASSPORT_DOCUMENT_NAME = /^STF_([A-Za-z0-9-]{1,80})_(PHOTO|FRONT|BACK)\.(jpe?g|png|webp)$/i;

async function buildLocalPassportDocumentPreview(
  groupId: string,
  files: File[],
  passports: PassportSubmission[],
  onProgress: (processed: number, total: number) => void,
): Promise<PassportDocumentImportPreview> {
  const byStaffCode = new Map<string, PassportSubmission>();
  passports.forEach((passport) => {
    const staffCode = getStaffCode(passport);
    if (staffCode) byStaffCode.set(staffCode, passport);
  });

  const accepted: PassportDocumentImportPreview["accepted_documents"] = [];
  const rejected: PassportDocumentImportPreview["rejected_documents"] = [];
  const seen = new Set<string>();
  const chunkSize = 300;

  for (let index = 0; index < files.length; index += chunkSize) {
    for (const file of files.slice(index, index + chunkSize)) {
      const match = PASSPORT_DOCUMENT_NAME.exec(file.name);
      if (!match) {
        rejected.push({ filename: file.name, accepted: false, reason: "Expected STF_<staffcode>_PHOTO, _FRONT, or _BACK image name" });
        continue;
      }
      const staffCode = match[1].toUpperCase();
      const documentType = match[2].toLowerCase() as "photo" | "front" | "back";
      const passenger = byStaffCode.get(staffCode);
      if (!passenger) {
        rejected.push({ filename: file.name, staff_code: staffCode, document_type: documentType, accepted: false, reason: "Staff code was not found in this group" });
        continue;
      }
      const duplicateKey = `${passenger.id}:${documentType}`;
      if (seen.has(duplicateKey)) {
        rejected.push({ filename: file.name, staff_code: staffCode, document_type: documentType, accepted: false, reason: "Duplicate document type for this passenger" });
        continue;
      }
      seen.add(duplicateKey);
      accepted.push({
        filename: file.name,
        staff_code: staffCode,
        document_type: documentType,
        passenger_id: passenger.id,
        passenger_name: passenger.client_name,
        accepted: true,
      });
    }
    onProgress(Math.min(index + chunkSize, files.length), files.length);
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  }

  return {
    group_id: groupId,
    total_count: accepted.length + rejected.length,
    accepted_count: accepted.length,
    rejected_count: rejected.length,
    accepted_documents: accepted,
    rejected_documents: rejected,
  };
}

function getStaffCode(passport: PassportSubmission) {
  const metadataCode = passport.staff_metadata?.staff_code ?? passport.staff_metadata?.staffcode;
  const fieldCode = getStringField(passport.confirmed_fields ?? passport.extracted_fields, "staff_code");
  const value = metadataCode || fieldCode;
  return value ? String(value).trim().toUpperCase() : "";
}

function PassportDocumentImportProgress({
  processed,
  total,
  label,
}: {
  processed: number;
  total: number;
  label: string;
}) {
  const percentage = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const unit = total > 1024 * 1024 ? "bytes" : "files";
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Passport document import</h2>
            <p className="mt-1 text-sm text-slate-500">{label}</p>
          </div>
          <div className="text-sm font-semibold text-blue-700">{percentage}%</div>
        </div>
        <div className="mt-5 h-3 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-blue-600 transition-all duration-150" style={{ width: `${Math.max(4, percentage)}%` }} />
        </div>
        <div className="mt-3 text-sm text-slate-500">
          {unit === "bytes"
            ? `${formatBytes(processed)} of ${formatBytes(total)}`
            : `${processed.toLocaleString()} of ${total.toLocaleString()} files checked`}
        </div>
      </div>
    </div>
  );
}

function PassportDocumentImportDialog({
  preview,
  passports,
  saving,
  onClose,
  onSave,
}: {
  preview: PassportDocumentImportPreview;
  passports: PassportSubmission[];
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
}) {
  const [step, setStep] = useState<"distribution" | "documents">("distribution");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="flex max-h-[85vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="border-b border-slate-200 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Passport document distribution</h2>
          <p className="mt-1 text-sm text-slate-500">
            {step === "distribution"
              ? `${preview.accepted_count} accepted, ${preview.rejected_count} rejected. Only accepted files will be saved.`
              : "Review every person against passport pic, passport front, and passport back before saving."}
          </p>
        </div>
        <div className="overflow-y-auto p-6">
          {step === "distribution" ? (
            <div className="grid gap-5 md:grid-cols-2">
              <section>
                <h3 className="mb-2 text-sm font-semibold text-emerald-800">Accepted ({preview.accepted_count})</h3>
                <div className="space-y-2">
                  {preview.accepted_documents.map((item) => (
                    <div key={`${item.filename}-${item.document_type}`} className="rounded-lg border border-emerald-100 bg-emerald-50 p-3 text-sm">
                      <div className="font-medium text-slate-800">{item.filename}</div>
                      <div className="mt-1 text-emerald-800">{item.passenger_name} - {item.document_type}</div>
                    </div>
                  ))}
                  {preview.accepted_count === 0 && <p className="text-sm text-slate-500">No files can be saved.</p>}
                </div>
              </section>
              <section>
                <h3 className="mb-2 text-sm font-semibold text-red-800">Rejected ({preview.rejected_count})</h3>
                <div className="space-y-2">
                  {preview.rejected_documents.map((item, index) => (
                    <div key={`${item.filename}-${index}`} className="rounded-lg border border-red-100 bg-red-50 p-3 text-sm">
                      <div className="font-medium text-slate-800">{item.filename}</div>
                      <div className="mt-1 text-red-700">{item.reason}</div>
                    </div>
                  ))}
                  {preview.rejected_count === 0 && <p className="text-sm text-slate-500">All files passed validation.</p>}
                </div>
              </section>
            </div>
          ) : (
            <PassportDocumentMatrix passports={passports} preview={preview} />
          )}
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <Button type="button" variant="outline" disabled={saving} onClick={onClose}>Cancel</Button>
          {step === "distribution" ? (
            <Button type="button" disabled={preview.accepted_count === 0} onClick={() => setStep("documents")}>
              Next
            </Button>
          ) : (
            <>
              <Button type="button" variant="secondary" disabled={saving} onClick={() => setStep("distribution")}>Back</Button>
              <Button type="button" disabled={saving || preview.accepted_count === 0} onClick={onSave}>
                {saving ? "Saving accepted files" : `Upload accepted (${preview.accepted_count})`}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 MB";
  const mb = bytes / (1024 * 1024);
  if (mb < 1) return `${Math.round(bytes / 1024)} KB`;
  return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`;
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

function TripDetailsDialog({
  form,
  isLoading,
  onChange,
  onClose,
  onSave,
}: {
  form: {
    name: string;
    destination: string;
    travel_date: string;
    return_date: string;
    departure_cities: string[];
    notes: string;
  };
  isLoading: boolean;
  onChange: (form: {
    name: string;
    destination: string;
    travel_date: string;
    return_date: string;
    departure_cities: string[];
    notes: string;
  }) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const [cityInput, setCityInput] = useState("");
  const updateField = (key: keyof typeof form, value: string) => {
    onChange({ ...form, [key]: value });
  };
  const addCity = () => {
    const nextCity = normalizeCity(cityInput);
    if (!nextCity) return;
    onChange({ ...form, departure_cities: normalizeCities([...form.departure_cities, nextCity]) });
    setCityInput("");
  };
  const removeCity = (city: string) => {
    onChange({ ...form, departure_cities: form.departure_cities.filter((item) => item !== city) });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Edit Trip Details</h2>
          <p className="mt-1 text-sm text-slate-500">These details appear in group views, search, filters, and exports.</p>
        </div>
        <div className="grid max-h-[70vh] gap-4 overflow-y-auto p-6 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Group Name</span>
            <Input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Destination</span>
            <Input value={form.destination} onChange={(event) => updateField("destination", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Travel Date</span>
            <Input type="date" value={form.travel_date} onChange={(event) => updateField("travel_date", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Return Date</span>
            <Input type="date" value={form.return_date} onChange={(event) => updateField("return_date", event.target.value)} />
          </label>
          <label className="space-y-2 sm:col-span-2">
            <span className="text-sm font-medium text-slate-700">Departure Cities</span>
            <div className="flex gap-2">
              <Input
                value={cityInput}
                onChange={(event) => setCityInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addCity();
                  }
                }}
                placeholder="e.g. Delhi, Chennai, Mumbai"
              />
              <Button type="button" variant="secondary" onClick={addCity}>
                Add
              </Button>
            </div>
            {form.departure_cities.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {form.departure_cities.map((city) => (
                  <button
                    key={city}
                    type="button"
                    onClick={() => removeCity(city)}
                    className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-800 transition hover:bg-blue-100"
                  >
                    {city}
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                ))}
              </div>
            )}
          </label>
          <label className="space-y-2 sm:col-span-2">
            <span className="text-sm font-medium text-slate-700">Notes</span>
            <textarea
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              rows={4}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button type="button" onClick={onSave} isLoading={isLoading}>
            Save Details
          </Button>
        </div>
      </div>
    </div>
  );
}

function normalizeCity(value: string) {
  return value.trim().replace(/\s+/g, " ").slice(0, 120);
}

function formatMetadataLabel(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function normalizeCities(values: string[]) {
  const seen = new Set<string>();
  const cities: string[] = [];
  for (const value of values) {
    const city = normalizeCity(value);
    if (!city) continue;
    const key = city.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cities.push(city);
  }
  return cities;
}
