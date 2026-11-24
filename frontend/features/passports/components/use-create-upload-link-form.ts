import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { invalidateBrandingImages, saveBrandingImage, type ImageDraft } from "@/features/branding/api/branding-images.api";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { selectUser, selectUserRole, useAuthStore } from "@/stores/auth.store";
import type { CompanyWorkspace } from "@/features/companies/hooks/use-company-workspace";
import type { CompanyReference } from "@/features/companies/types";
import { getPassportUploadTargets, type PassportUploadTarget } from "@/lib/utils/public-url";
import { createUploadLinkSchema, type CreateUploadLinkFormData, type CreateUploadLinkFormInput } from "../schemas/upload-link.schema";
import { useCreateUploadLink } from "../hooks/use-upload-links";
import { getUploadLinkSettings } from "./upload-link-settings-model";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { normalizeCities } from "../utils/passport-group-trip";
import { capturePrivateOperationOwner, RequestOwnerChangedError } from "@/lib/api/request-owner";
import { createUploadLinkDefaults } from "./create-upload-link-defaults";
import type { CreateUploadLinkModalProps } from "./create-upload-link-modal";

export function useCreateUploadLinkForm({ isOpen, onClose, workspace }: CreateUploadLinkModalProps & { workspace: CompanyWorkspace }) {
  const role = useAuthStore(selectUserRole);
  const user = useAuthStore(selectUser);
  const [company, setCompany] = useState<CompanyReference | null>(null);
  const agencyId = workspace.agencyId;
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);
  const [generatedTargets, setGeneratedTargets] = useState<PassportUploadTarget[]>([]);
  const [createdImportGroupId, setCreatedImportGroupId] = useState<string | null>(null);
  const [copiedTargetKey, setCopiedTargetKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [banner, setBanner] = useState<ImageDraft>();
  const [savingBanner, setSavingBanner] = useState(false);
  const [bannerRetryGroupId, setBannerRetryGroupId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const copiedTimerRef = useRef<number | null>(null);
  const copiedOperationRef = useRef(0);
  const titleId = useId();
  const { tryEnter: tryEnterCreate, leave: leaveCreate } = useSingleFlightGate();
  const { mutateAsync: createUploadLink, isPending: creating } = useCreateUploadLink();
  const isPending = creating || savingBanner;
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<CreateUploadLinkFormInput, unknown, CreateUploadLinkFormData>({
    resolver: zodResolver(createUploadLinkSchema),
    defaultValues: createUploadLinkDefaults(),
  });
  const importOnly = useWatch({ control, name: "import_only" }) === true;
  const settings = useWatch({ control, compute: (values) => getUploadLinkSettings("upload_configuration" in values ? values : {}) });
  const whatsappBroadcastGroupIds = useWatch({
    control,
    name: "whatsapp_broadcast_group_ids",
  }) ?? [];
  const matchingFieldsByBroadcast = useWatch({
    control,
    name: "matching_fields_by_broadcast",
  }) ?? {};
  useEffect(() => () => {
    copiedOperationRef.current++;
    if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
  }, []);
  const handleClose = useCallback(() => {
    if (isPending) return;
    copiedOperationRef.current++;
    if (copiedTimerRef.current !== null) {
      window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = null;
    }
    reset();
    setCompany(null);
    setGeneratedTargets([]);
    setCreatedImportGroupId(null);
    setCopiedTargetKey(null);
    setActionError(null);
    setBanner(undefined);
    setBannerRetryGroupId(null);
    onClose();
  }, [isPending, onClose, reset]);
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen, canClose: !isPending, onClose: handleClose });
  const onSubmit = async (data: CreateUploadLinkFormData) => {
    if (!agencyId || isPending || !tryEnterCreate()) return;
    setActionError(null);
    try {
      const owner = capturePrivateOperationOwner();
      const result = await createUploadLink({
        ...data,
        ...(user?.role === "super_admin" && agencyId ? { agency_id: agencyId } : {}),
        name: data.name.trim(),
        destination: data.destination.trim(),
        travel_date: data.travel_date,
        return_date: data.return_date,
        departure_cities: data.nearest_international_airport_enabled
          ? normalizeCities(data.departure_cities)
          : [],
        whatsapp_broadcast_group_ids: canAccessWhatsApp
          ? data.whatsapp_broadcast_group_ids
          : [],
        matching_fields_by_broadcast: canAccessWhatsApp
          ? data.matching_fields_by_broadcast
          : {},
      });
      owner.assertCurrent();
      if (banner instanceof File) {
        setSavingBanner(true);
        try {
          await saveBrandingImage("group-banner", result.id, agencyId, banner, undefined, owner.requestConfig.expectedOwnerUserId);
          owner.assertCurrent();
          await invalidateBrandingImages(queryClient);
          owner.assertCurrent();
        } catch (error) {
          owner.assertCurrent();
          if (error instanceof RequestOwnerChangedError) throw error;
          setBannerRetryGroupId(result.id);
          setActionError("Your group was created, but the banner could not be uploaded. Retry below or add it later from the group header.");
        } finally { setSavingBanner(false); }
      }
      if (data.import_only) {
        setCreatedImportGroupId(result.id);
      } else {
        setGeneratedTargets(getPassportUploadTargets(result.token));
      }
    } catch (error) {
      if (error instanceof RequestOwnerChangedError) return;
      setActionError(
        "The upload link could not be created. Check your connection and try again.",
      );
    } finally {
      leaveCreate();
    }
  };
  const copyTarget = async (target: PassportUploadTarget) => {
    const operation = ++copiedOperationRef.current;
    setActionError(null);
    try {
      await copyTextToClipboard(target.url);
      if (operation !== copiedOperationRef.current) return;
      setCopiedTargetKey(target.key);
      if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = window.setTimeout(() => {
        setCopiedTargetKey((current) => current === target.key ? null : current);
        copiedTimerRef.current = null;
      }, 2000);
    } catch {
      if (operation !== copiedOperationRef.current) return;
      setActionError(
        "The link could not be copied automatically. Select the link text and copy it manually.",
      );
    }
  };
  const hasGeneratedTargets = generatedTargets.length > 0;
  const isCreated = hasGeneratedTargets || createdImportGroupId !== null;
  const retryBanner = async () => {
    if (!bannerRetryGroupId || savingBanner || banner === undefined || !tryEnterCreate()) return;
    setSavingBanner(true);
    try {
      const owner = capturePrivateOperationOwner();
      await saveBrandingImage("group-banner", bannerRetryGroupId, agencyId ?? undefined, banner, undefined, owner.requestConfig.expectedOwnerUserId);
      owner.assertCurrent();
      await invalidateBrandingImages(queryClient);
      owner.assertCurrent();
      setBannerRetryGroupId(null); setActionError(null);
    } catch (error) {
      if (!(error instanceof RequestOwnerChangedError)) setActionError("The banner could not be uploaded. Retry when ready; your group is already saved.");
    }
    finally { setSavingBanner(false); leaveCreate(); }
  };
  return {
    dialogRef,
    handleKeyDown,
    titleId,
    isPending,
    createdImportGroupId,
    hasGeneratedTargets,
    handleClose,
    agencyId,
    isCreated,
    generatedTargets,
    copyTarget,
    copiedTargetKey,
    actionError,
    bannerRetryGroupId,
    banner,
    setBanner,
    savingBanner,
    handleSubmit,
    onSubmit,
    importOnly,
    setValue,
    company,
    setCompany,
    errors,
    register,
    settings,
    canAccessWhatsApp,
    whatsappBroadcastGroupIds,
    matchingFieldsByBroadcast,
    retryBanner
  };
}

export type CreateUploadLinkState = ReturnType<typeof useCreateUploadLinkForm>;

function useSingleFlightGate() {
  const inFlightRef = useRef(false);
  const tryEnter = useCallback(() => {
    if (inFlightRef.current) return false;
    inFlightRef.current = true;
    return true;
  }, []);
  const leave = useCallback(() => {
    inFlightRef.current = false;
  }, []);
  return { tryEnter, leave };
}
