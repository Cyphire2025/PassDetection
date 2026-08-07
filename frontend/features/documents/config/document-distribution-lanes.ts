import type {
  DistributionDocumentType,
  DocumentDistributionGroup,
} from "@/types/document-distribution.types";

export type DocumentDistributionCategory = "visa" | "flight_tickets";
export type FlightTicketScope = "international" | "domestic";
export type FlightTicketLeg = "onward" | "return";

type AssignedCountField = {
  [Key in keyof DocumentDistributionGroup]: Key extends `${string}_assigned_count`
    ? Key
    : never;
}[keyof DocumentDistributionGroup];

export interface DocumentDistributionLane {
  key:
    | "visa"
    | "international_onward"
    | "international_return"
    | "domestic_onward"
    | "domestic_return";
  documentType: DistributionDocumentType;
  category: DocumentDistributionCategory;
  title: string;
  workflowLabel: string;
  uploadLabel: string;
  description: string;
  assignedCountField: AssignedCountField;
  scope?: FlightTicketScope;
  leg?: FlightTicketLeg;
}

export const DOCUMENT_DISTRIBUTION_LANES = {
  visa: {
    key: "visa",
    documentType: "visa",
    category: "visa",
    title: "Visa",
    workflowLabel: "Visa",
    uploadLabel: "visa",
    description: "Upload, match, review, and deliver visa PDFs for this group.",
    assignedCountField: "visa_assigned_count",
  },
  international_onward: {
    key: "international_onward",
    documentType: "flight_ticket",
    category: "flight_tickets",
    title: "International Onward",
    workflowLabel: "International Onward ticket",
    uploadLabel: "international onward flight ticket",
    description: "Outbound international flight tickets for this group.",
    assignedCountField: "flight_ticket_assigned_count",
    scope: "international",
    leg: "onward",
  },
  international_return: {
    key: "international_return",
    documentType: "flight_ticket_arrival",
    category: "flight_tickets",
    title: "International Return",
    workflowLabel: "International Return ticket",
    uploadLabel: "international return flight ticket",
    description: "Return international flight tickets for this group.",
    assignedCountField: "flight_ticket_arrival_assigned_count",
    scope: "international",
    leg: "return",
  },
  domestic_onward: {
    key: "domestic_onward",
    documentType: "flight_ticket_domestic",
    category: "flight_tickets",
    title: "Domestic Onward",
    workflowLabel: "Domestic Onward ticket",
    uploadLabel: "domestic onward flight ticket",
    description: "Outbound domestic flight tickets for this group.",
    assignedCountField: "flight_ticket_domestic_assigned_count",
    scope: "domestic",
    leg: "onward",
  },
  domestic_return: {
    key: "domestic_return",
    documentType: "flight_ticket_domestic_arrival",
    category: "flight_tickets",
    title: "Domestic Return",
    workflowLabel: "Domestic Return ticket",
    uploadLabel: "domestic return flight ticket",
    description: "Return domestic flight tickets for this group.",
    assignedCountField: "flight_ticket_domestic_arrival_assigned_count",
    scope: "domestic",
    leg: "return",
  },
} as const satisfies Record<string, DocumentDistributionLane>;

export const VISA_DISTRIBUTION_LANE = DOCUMENT_DISTRIBUTION_LANES.visa;

const DISTRIBUTION_LANE_BY_DOCUMENT_TYPE = {
  visa: DOCUMENT_DISTRIBUTION_LANES.visa,
  flight_ticket: DOCUMENT_DISTRIBUTION_LANES.international_onward,
  flight_ticket_arrival: DOCUMENT_DISTRIBUTION_LANES.international_return,
  flight_ticket_domestic: DOCUMENT_DISTRIBUTION_LANES.domestic_onward,
  flight_ticket_domestic_arrival: DOCUMENT_DISTRIBUTION_LANES.domestic_return,
} as const satisfies Record<DistributionDocumentType, DocumentDistributionLane>;

const FLIGHT_LANE_BY_ROUTE = {
  international: {
    onward: DOCUMENT_DISTRIBUTION_LANES.international_onward,
    return: DOCUMENT_DISTRIBUTION_LANES.international_return,
  },
  domestic: {
    onward: DOCUMENT_DISTRIBUTION_LANES.domestic_onward,
    return: DOCUMENT_DISTRIBUTION_LANES.domestic_return,
  },
} as const;

export function isFlightTicketScope(value: string): value is FlightTicketScope {
  return value === "international" || value === "domestic";
}

export function isFlightTicketLeg(value: string): value is FlightTicketLeg {
  return value === "onward" || value === "return";
}

export function getFlightDistributionLane(
  scope: FlightTicketScope,
  leg: FlightTicketLeg,
): DocumentDistributionLane {
  return FLIGHT_LANE_BY_ROUTE[scope][leg];
}

export function getAssignedCount(
  group: DocumentDistributionGroup | undefined,
  lane: DocumentDistributionLane,
): number {
  return group?.[lane.assignedCountField] ?? 0;
}

export function distributionDocumentLabel(documentType: string): string {
  const lane = DISTRIBUTION_LANE_BY_DOCUMENT_TYPE[
    documentType as DistributionDocumentType
  ];
  return lane?.title ?? "Travel Document";
}

export function distributionDocumentUploadLabel(documentType: string): string {
  const lane = DISTRIBUTION_LANE_BY_DOCUMENT_TYPE[
    documentType as DistributionDocumentType
  ];
  return lane?.uploadLabel ?? "travel document";
}
