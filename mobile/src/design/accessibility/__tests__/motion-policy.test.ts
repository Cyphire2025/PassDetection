import { navigationAnimation } from '../use-reduced-motion';

test('disables navigation motion when the device requests reduced motion', () => {
  expect(navigationAnimation(true, 'slide_from_right')).toBe('none');
  expect(navigationAnimation(false, 'slide_from_right')).toBe('slide_from_right');
});
