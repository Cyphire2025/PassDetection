import {
  beginRequiredPreparation,
  cancelRequiredPreparation,
  completeRequiredPreparation,
  isRequiredPreparationActive,
} from '../required-preparation-lease';

afterEach(() => cancelRequiredPreparation());

test('only the active authenticated session owns required preparation', () => {
  beginRequiredPreparation('session-a');
  expect(isRequiredPreparationActive('session-a')).toBe(true);
  expect(isRequiredPreparationActive('session-b')).toBe(false);

  completeRequiredPreparation('session-b');
  expect(isRequiredPreparationActive('session-a')).toBe(true);
  completeRequiredPreparation('session-a');
  expect(isRequiredPreparationActive('session-a')).toBe(false);
});

test('a new account boundary supersedes and cancellation clears the old lease', () => {
  beginRequiredPreparation('session-a');
  beginRequiredPreparation('session-b');
  expect(isRequiredPreparationActive('session-a')).toBe(false);
  expect(isRequiredPreparationActive('session-b')).toBe(true);
  cancelRequiredPreparation('session-b');
  expect(isRequiredPreparationActive('session-b')).toBe(false);
});
