import type { AttendanceSession } from '../api/coordinator-contracts';

const CATEGORY_LABELS: Record<string, string> = {
  itinerary_pdf: 'Itinerary',
  travel_tips: 'Travel tips',
  common_instructions: 'Common instructions',
  destination: 'Destination information',
  emergency: 'Emergency information',
  hotel: 'Hotel information',
  flight_summary: 'Flight summary',
  meeting_point: 'Meeting points',
  dress_code: 'Dress code',
  baggage: 'Baggage guidance',
  other: 'Other documents',
};

const CATEGORY_ORDER = [
  'itinerary_pdf',
  'travel_tips',
  'common_instructions',
  'destination',
  'emergency',
  'hotel',
  'flight_summary',
  'meeting_point',
  'dress_code',
  'baggage',
  'other',
];

export function coordinatorDocumentCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category
    .split('_')
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');
}

export function coordinatorDocumentCategoryOrder(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

export function visibleAttendanceSessions(items: AttendanceSession[]): AttendanceSession[] {
  return items
    .filter((session) => session.status === 'active' || session.status === 'completed')
    .sort((left, right) => {
      if (left.status !== right.status) return left.status === 'active' ? -1 : 1;
      const leftTime = Date.parse(left.completed_at ?? left.started_at ?? '') || 0;
      const rightTime = Date.parse(right.completed_at ?? right.started_at ?? '') || 0;
      return rightTime - leftTime;
    });
}
