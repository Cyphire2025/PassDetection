import { useQuery } from '@tanstack/react-query';

import {
  loadMeal,
  loadQr,
  loadReadiness,
  loadRoom,
  refreshAnnouncements,
  refreshCommonDocuments,
  refreshDocuments,
} from '../data/content-repository';

export function useAnnouncements(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-announcements', tripId],
    queryFn: () => refreshAnnouncements(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useDocuments(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-documents', tripId],
    queryFn: () => refreshDocuments(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useCommonDocuments(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-common-documents', tripId],
    queryFn: () => refreshCommonDocuments(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useQr(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-qr', tripId],
    queryFn: () => loadQr(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useRoom(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-room', tripId],
    queryFn: () => loadRoom(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useMeal(tripId: string | null) {
  return useQuery({
    queryKey: ['trip-meal', tripId],
    queryFn: () => loadMeal(tripId!),
    enabled: Boolean(tripId),
  });
}

export function useReadiness(tripId: string | null) {
  return useQuery({
    queryKey: ['manager-readiness', tripId],
    queryFn: () => loadReadiness(tripId!),
    enabled: Boolean(tripId),
  });
}
