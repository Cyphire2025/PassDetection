import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  TourOperationsArchitecture,
  TourCoordinator,
  CreateCoordinatorRequest,
  TourGroup,
  TourPassenger,
  TourPassengerDetail,
} from "./operations-tour.types";

export const tourOperationsApi = {
  tourOperationsArchitecture: async (): Promise<TourOperationsArchitecture> => {
    const { data } = await apiClient.get<TourOperationsArchitecture>(API_ENDPOINTS.tourOperations.architecture);
    return data;
  },

  tourCoordinators: async (): Promise<TourCoordinator[]> => {
    const { data } = await apiClient.get<TourCoordinator[]>(API_ENDPOINTS.tourOperations.coordinators);
    return data;
  },

  createTourCoordinator: async (body: CreateCoordinatorRequest): Promise<TourCoordinator> => {
    const { data } = await apiClient.post<TourCoordinator>(API_ENDPOINTS.tourOperations.coordinators, body);
    return data;
  },

  tourGroups: async (assignmentEligibleOnly = false): Promise<TourGroup[]> => {
    const { data } = await apiClient.get<TourGroup[]>(API_ENDPOINTS.tourOperations.groups, {
      params: assignmentEligibleOnly ? { assignment_eligible_only: true } : undefined,
    });
    return data;
  },

  assignTourGroupCoordinators: async (groupId: string, coordinatorIds: string[]): Promise<TourGroup> => {
    const { data } = await apiClient.put<TourGroup>(API_ENDPOINTS.tourOperations.groupCoordinators(groupId), {
      coordinator_ids: coordinatorIds,
    });
    return data;
  },

  tourGroupPassengers: async (groupId: string): Promise<TourPassenger[]> => {
    const { data } = await apiClient.get<TourPassenger[]>(API_ENDPOINTS.tourOperations.groupPassengers(groupId));
    return data;
  },

  assignTourGroupPassengers: async (
    groupId: string,
    passengerIds: string[],
    coordinatorId: string | null,
  ): Promise<TourPassenger[]> => {
    const { data } = await apiClient.put<TourPassenger[]>(API_ENDPOINTS.tourOperations.assignGroupPassengers(groupId), {
      passenger_ids: passengerIds,
      coordinator_id: coordinatorId,
    });
    return data;
  },

  myTourGroups: async (): Promise<TourGroup[]> => {
    const { data } = await apiClient.get<TourGroup[]>(API_ENDPOINTS.tourOperations.myGroups);
    return data;
  },

  myTourGroupPassengers: async (groupId: string): Promise<TourPassenger[]> => {
    const { data } = await apiClient.get<TourPassenger[]>(API_ENDPOINTS.tourOperations.myGroupPassengers(groupId));
    return data;
  },

  myTourGroupPassenger: async (groupId: string, passengerId: string): Promise<TourPassengerDetail> => {
    const { data } = await apiClient.get<TourPassengerDetail>(
      API_ENDPOINTS.tourOperations.myGroupPassenger(groupId, passengerId),
    );
    return data;
  },
};
