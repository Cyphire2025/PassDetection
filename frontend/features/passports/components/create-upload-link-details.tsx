import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ImageUploadField } from "@/features/branding/components/image-upload-field";
import { CompanyPicker } from "@/features/companies/components/company-picker";
import { getUploadLinkSettingsError, UploadLinkSettings, type UploadLinkSettingsValue } from "./upload-link-settings";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";
import { TripTimeZoneField } from "./trip-timezone-field";
import type { CreateUploadLinkState } from "./use-create-upload-link-form";

export function CreateUploadLinkDetails({ state }: { state: CreateUploadLinkState }) {
  const {
    handleSubmit,
    onSubmit,
    isPending,
    importOnly,
    setValue,
    agencyId,
    company,
    setCompany,
    errors,
    register,
    banner,
    setBanner,
    settings,
    canAccessWhatsApp,
    whatsappBroadcastGroupIds,
    matchingFieldsByBroadcast,
    actionError,
    handleClose
  } = state;
  return (<form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
    <fieldset disabled={isPending} className="space-y-2">
      <legend className="mb-2 text-sm font-semibold text-slate-900">Group purpose</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <label
          className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${!importOnly ? "border-blue-500 bg-blue-50" : "border-slate-200"}`}
        >
          <input
            type="radio"
            name="group-purpose"
            checked={!importOnly}
            onChange={() => setValue("import_only", false, { shouldDirty: true, shouldValidate: true })}
            className="mt-1"
          />
          <span><span className="block text-sm font-medium text-slate-900">Collect documents</span><span className="mt-1 block text-xs text-slate-600">Share a link for passengers to submit their details.</span></span>
        </label>
        <label
          className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${importOnly ? "border-blue-500 bg-blue-50" : "border-slate-200"}`}
        >
          <input
            type="radio"
            name="group-purpose"
            checked={importOnly}
            onChange={() => setValue("import_only", true, { shouldDirty: true, shouldValidate: true })}
            className="mt-1"
          />
          <span><span className="block text-sm font-medium text-slate-900">Import data</span><span className="mt-1 block text-xs text-slate-600">Create a group for your final Excel list. You can import after creation.</span></span>
        </label>
      </div>
    </fieldset>
    <h3 className="text-sm font-semibold text-slate-900">Group Details</h3>
    <CompanyPicker
      agencyId={agencyId}
      value={company}
      onChange={(selected) => {
        setCompany(selected);
        setValue("company_id", selected.id, { shouldDirty: true, shouldValidate: true });
      }}
      disabled={isPending || !agencyId}
      required
      error={errors.company_id?.message}
    />
    <Input
      label="Group Name"
      placeholder="e.g. Summer Europe Tour 2026"
      {...register("name")}
      error={errors.name?.message}
      data-dialog-initial-focus
    />
    <ImageUploadField kind="banner" value={banner} onChange={setBanner} disabled={isPending} />

    <div className="grid gap-4 sm:grid-cols-2">
      <Input
        label="Destination"
        placeholder="e.g. Dubai"
        {...register("destination")}
        error={errors.destination?.message}
        required
      />
      <Input
        label="Travel/Departure Date"
        type="date"
        {...register("travel_date")}
        error={errors.travel_date?.message}
        required
      />
      <Input
        label="Return Date"
        type="date"
        {...register("return_date")}
        error={errors.return_date?.message}
        required
      />
      <TripTimeZoneField
        {...register("timezone")}
        error={errors.timezone?.message}
        required
      />
    </div>

    {!importOnly && <UploadLinkSettings
      value={settings}
      disabled={isPending}
      error={
        ("upload_configuration" in errors && errors.upload_configuration)
          || ("departure_cities" in errors && errors.departure_cities)
          || ("custom_questions" in errors && errors.custom_questions)
          || ("custom_details" in errors && errors.custom_details)
          ? getUploadLinkSettingsError(settings)
          : undefined
      }
      onChange={(patch) => {
        for (const [key, value] of Object.entries(patch)) {
          setValue(key as keyof UploadLinkSettingsValue, value, { shouldDirty: true, shouldValidate: true });
        }
      }}
    />}

    {!importOnly && canAccessWhatsApp && (
      <WhatsAppBroadcastSelector
        selectedIds={whatsappBroadcastGroupIds}
        onChange={(ids) => setValue(
          "whatsapp_broadcast_group_ids",
          ids,
          { shouldDirty: true, shouldValidate: true },
        )}
        selectedMatchingFields={matchingFieldsByBroadcast}
        onMatchingFieldsChange={(fields) => setValue(
          "matching_fields_by_broadcast",
          fields,
          { shouldDirty: true, shouldValidate: true },
        )}
        disabled={isPending}
        description="Optional. Link the group to one or more existing broadcasts now so recipient submissions can be tracked from the beginning."
      />
    )}

    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
      {importOnly ? "Only the group details above are needed. After creation, import your Excel file from the group workspace." : <>
        This will generate:
        <div className="mt-2">1. An upload link for clients on phones or browsers</div>
      </>}
    </div>

    {actionError && (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {actionError}
      </div>
    )}

    <div className="flex justify-end gap-3 pt-4">
      <Button type="button" variant="secondary" onClick={handleClose} disabled={isPending}>
        Cancel
      </Button>
      <Button type="submit" disabled={isPending || !agencyId}>
        {isPending ? "Creating..." : importOnly ? "Create Group" : "Generate Links"}
      </Button>
    </div>
  </form>);
}
