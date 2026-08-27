import { DeleteEnrollmentResponseSchema } from '../contracts';

const response = {
  enrollment_status: 'deleted',
  removed_search_data: false,
  local_downloads_affected: false,
  provider_deletion_status: 'failed',
  provider_deletion_retryable: true,
  deleted_at: '2026-08-23T12:00:00Z',
} as const;

describe('My Photos enrollment deletion response', () => {
  it('accepts the finalized provider cleanup state without deleting local downloads', () => {
    expect(DeleteEnrollmentResponseSchema.parse(response)).toEqual(response);
  });

  it('rejects unknown provider payload fields', () => {
    expect(() => DeleteEnrollmentResponseSchema.parse({
      ...response,
      provider_response: { raw: true },
    })).toThrow();
  });
});
