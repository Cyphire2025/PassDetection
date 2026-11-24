"use client";
import { useRef, useState } from "react";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useConfirmPassportSubmission,
  usePassportSubmission,
  useReextractPassportSubmission,
  useRetryPassportAiVerification,
  useStaffApprovePassportSubmission,
} from "../hooks/use-passports";
import type { StaffApprovalFeedback } from "../utils/passport-review";
import { passportsApi, type PassportImageType } from "../api/passports.api";
import { getReextractFeedback } from "../utils/passport-reextract";
import { canEditPassportImages } from "../utils/passport-image-crop-permissions";
import { validatePassportLibraryImage } from "../utils/passport-image-library";
import { usePassportDetailNavigation } from "./use-passport-detail-navigation";
import { readManualImageChangeError } from "./passport-review-model";
import type { ReextractFeedback } from "./passport-review-types";

export function usePassportDetailController(id: string, navigationQuery: string) {
  const { data, isLoading, error, refetch } = usePassportSubmission(id);
  const confirmMutation = useConfirmPassportSubmission(id);
  const staffApproveMutation = useStaffApprovePassportSubmission(id);
  const retryAiVerificationMutation = useRetryPassportAiVerification(id);
  const reextractMutation = useReextractPassportSubmission();
  const currentUser = useAuthStore(selectUser);
  const canCropPassportImages = canEditPassportImages(currentUser?.role);
  const [formError, setFormError] = useState<string | null>(null);
  const [approvalFeedback, setApprovalFeedback] = useState<StaffApprovalFeedback | null>(null);
  const [reextractFeedback, setReextractFeedback] = useState<ReextractFeedback | null>(null);
  const [cropEditor, setCropEditor] = useState<{
    imageType: PassportImageType;
    label: string;
    returnFocusTarget: HTMLButtonElement;
  } | null>(null);
  const [imageRevision, setImageRevision] = useState(0);
  const [changingImageType, setChangingImageType] =
    useState<PassportImageType | null>(null);
  const [imageChangeErrors, setImageChangeErrors] = useState<
    Partial<Record<PassportImageType, string>>
  >({});
  const reextractInFlightRef = useRef(false);
  const imageChangeInFlightRef = useRef(false);
  const navigation = usePassportDetailNavigation(data, navigationQuery, currentUser?.id, Boolean(cropEditor));
  const handleReextract = async () => {
    if (!data || reextractMutation.isPending || reextractInFlightRef.current) return;
    reextractInFlightRef.current = true;
    setFormError(null);
    setReextractFeedback({
      tone: "processing",
      message: "Re-extraction queued. Reading and verifying the saved passport image.",
    });
    try {
      const result = await reextractMutation.mutateAsync(data.id);
      if (result.outcome === "timed_out") {
        setReextractFeedback({
          tone: "warning",
          message: "Extraction or AI verification is still running. This page will keep refreshing automatically.",
        });
        return;
      }
      if (result.outcome === "failed") {
        setReextractFeedback({
          tone: "error",
          message: result.submission.error_message
            || "The saved image could not be extracted. It remains available for another retry.",
        });
        return;
      }
      setReextractFeedback(getReextractFeedback(result.submission));
    } catch (reextractError) {
      setReextractFeedback({
        tone: "error",
        message: reextractError instanceof Error
          ? reextractError.message
          : "Could not start re-extraction. Please try again.",
      });
    } finally {
      reextractInFlightRef.current = false;
    }
  };

  const handleManualImageChange = async (
    imageType: PassportImageType,
    file: File,
  ) => {
    if (!data || !canCropPassportImages || imageChangeInFlightRef.current) return;
    const validationError = validatePassportLibraryImage(file);
    if (validationError) {
      setImageChangeErrors((current) => ({
        ...current,
        [imageType]: validationError,
      }));
      return;
    }
    imageChangeInFlightRef.current = true;
    setChangingImageType(imageType);
    setImageChangeErrors((current) => {
      const next = { ...current };
      delete next[imageType];
      return next;
    });
    try {
      const metadata = await passportsApi.getImageCrop(data.id, imageType);
      await passportsApi.uploadImageLibraryImage(
        data.id,
        imageType,
        file,
        metadata.revision,
      );
      setImageRevision((current) => current + 1);
      await refetch();
    } catch (uploadError) {
      setImageChangeErrors((current) => ({
        ...current,
        [imageType]: readManualImageChangeError(uploadError),
      }));
    } finally {
      imageChangeInFlightRef.current = false;
      setChangingImageType(null);
    }
  };
  return {
    data, isLoading, error, refetch, currentUser, canCropPassportImages, confirmMutation, staffApproveMutation,
    retryAiVerificationMutation, reextractMutation, formError, setFormError, approvalFeedback, setApprovalFeedback,
    reextractFeedback, cropEditor, setCropEditor, imageRevision, setImageRevision, changingImageType,
    imageChangeErrors, navigation, handleReextract, handleManualImageChange,
  };
}

export type PassportDetailController = ReturnType<typeof usePassportDetailController>;
