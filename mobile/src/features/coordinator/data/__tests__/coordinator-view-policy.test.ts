import {
  coordinatorDocumentCategoryLabel,
  coordinatorDocumentCategoryOrder,
  visibleAttendanceSessions,
} from '../coordinator-view-policy';

describe('coordinator view policy', () => {
  it('keeps itinerary first and gives known categories stable headings', () => {
    expect(coordinatorDocumentCategoryOrder('itinerary_pdf')).toBe(0);
    expect(coordinatorDocumentCategoryOrder('travel_tips')).toBeLessThan(
      coordinatorDocumentCategoryOrder('other'),
    );
    expect(coordinatorDocumentCategoryLabel('itinerary_pdf')).toBe('Itinerary');
    expect(coordinatorDocumentCategoryLabel('travel_tips')).toBe('Travel tips');
    expect(coordinatorDocumentCategoryLabel('custom_brief')).toBe('Custom Brief');
  });

  it('shows only active and completed attendance activities, newest first', () => {
    const visible = visibleAttendanceSessions([
      {
        id: '00000000-0000-4000-8000-000000000001',
        name: 'Draft',
        status: 'draft',
        scanned_count: 0,
        assigned_count: 10,
        started_at: null,
        completed_at: null,
      },
      {
        id: '00000000-0000-4000-8000-000000000002',
        name: 'Older completed',
        status: 'completed',
        scanned_count: 9,
        assigned_count: 10,
        started_at: '2026-07-31T10:00:00.000Z',
        completed_at: '2026-07-31T11:00:00.000Z',
      },
      {
        id: '00000000-0000-4000-8000-000000000003',
        name: 'Current',
        status: 'active',
        scanned_count: 3,
        assigned_count: 10,
        started_at: '2026-08-02T10:00:00.000Z',
        completed_at: null,
      },
      {
        id: '00000000-0000-4000-8000-000000000004',
        name: 'Cancelled',
        status: 'cancelled',
        scanned_count: 0,
        assigned_count: 10,
        started_at: '2026-08-02T09:00:00.000Z',
        completed_at: null,
      },
    ]);

    expect(visible.map((session) => session.name)).toEqual(['Current', 'Older completed']);
  });
});
