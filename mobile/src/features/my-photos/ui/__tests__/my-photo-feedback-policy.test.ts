import { canSubmitMyPhotoFeedback } from '../my-photo-feedback-policy';

test('allows match feedback only for an authorized passenger-match row', () => {
  expect(canSubmitMyPhotoFeedback({
    match_id: '11111111-1111-4111-8111-111111111111',
    tier: 'best',
  })).toBe(true);
  expect(canSubmitMyPhotoFeedback({ match_id: null, tier: null })).toBe(false);
  expect(canSubmitMyPhotoFeedback({
    match_id: '11111111-1111-4111-8111-111111111111',
    tier: null,
  })).toBe(false);
});
