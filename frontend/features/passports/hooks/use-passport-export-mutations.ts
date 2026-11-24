import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useQueryClient } from "@tanstack/react-query";
import { passportsApi } from "../api/passports.api";
import type {
  PassportGroupExportRequest,
  PassportWhatsAppTrackingExportRequest,
  PassportSelectedImagesExportRequest,
  PassportSelectedGroupsExportRequest,
} from "../api/passports.api";

export function useExportPassportGroup() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (request: PassportGroupExportRequest, _context, owner) =>
      passportsApi.exportGroup(request, owner.requestConfig),
    onSuccess: (_result, request) => {
      queryClient.invalidateQueries({
        queryKey: ["passport-export-history", request.groupId, "passport_excel"],
      });
    },
  });
}

export function useExportPassportGroupImages() {
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (request: PassportGroupExportRequest, _context, owner) =>
      passportsApi.exportGroupImages(request, owner.requestConfig),
    onSuccess: (_result, request) => {
      queryClient.invalidateQueries({
        queryKey: ["passport-export-history", request.groupId, "passport_images"],
      });
    },
  });
}

export function useExportWhatsAppTracking() {
  return usePrivateMutation({
    mutationFn: (request: PassportWhatsAppTrackingExportRequest, _context, owner) =>
      passportsApi.exportWhatsAppTracking(request, owner.requestConfig),
  });
}

export function useExportSelectedPassports() {
  return usePrivateMutation({
    mutationFn: (submissionIds: string[], _context, owner) => passportsApi.exportSelectedPassports(submissionIds, owner.requestConfig),
  });
}

export function useExportSelectedPassportImages() {
  return usePrivateMutation({
    mutationFn: (request: PassportSelectedImagesExportRequest, _context, owner) =>
      passportsApi.exportSelectedGroupImages(request, owner.requestConfig),
  });
}

export function useExportSelectedGroups() {
  return usePrivateMutation({
    mutationFn: (request: PassportSelectedGroupsExportRequest, _context, owner) =>
      passportsApi.exportSelectedGroups(request, owner.requestConfig),
  });
}
