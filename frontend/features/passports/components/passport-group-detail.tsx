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
} from "../hooks/use-passports";

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
  const exportSelected = useExportSelectedPassports();
  const updateGroup = useUpdateUploadLink();
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
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

  const filteredPassports = useMemo(() => {
    return (data ?? []).filter((passport) => {
      if (statusFilter !== "all" && passport.status !== statusFilter) return false;
      const confidence = passport.overall_confidence ?? 0;
      if (qualityFilter === "low_confidence" && confidence > 0.5) return false;
      if (qualityFilter === "missing_passport" && getStringField(passport.extracted_fields, "passport_number")) return false;
      if (qualityFilter === "expiry_alert" && getExpiryStatus(passport) === "valid") return false;
      if (qualityFilter === "complete" && needsReextraction(passport)) return false;
      return true;
    });
  }, [data, qualityFilter, statusFilter]);

  const togglePassport = (passportId: string) => {
    setSelectedPassports((current) =>
      current.includes(passportId) ? current.filter((id) => id !== passportId) : [...current, passportId],
    );
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
                  setImportMessage(`Imported ${result.imported_count} passenger${result.imported_count === 1 ? "" : "s"}.`);
                },
                onError: (error) => {
                  const message = error instanceof Error ? error.message : "Import failed";
                  setImportMessage(message);
                },
              });
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
          action={{ label: "Reset Filters", onClick: () => { setSearch(""); setStatusFilter("all"); setQualityFilter("all"); } }}
        />
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

function needsReextraction(passport: PassportSubmission) {
  return (
    passport.status === "failed" ||
    !getStringField(passport.extracted_fields, "passport_number") ||
    (passport.overall_confidence ?? 0) <= 0.2
  );
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
