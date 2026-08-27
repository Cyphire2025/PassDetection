import { fireEvent, render } from '@testing-library/react-native';

import {
  PhotoDownloadPlanModal,
  type PhotoDownloadPlanPresentation,
} from '../photo-download-plan-modal';

const PLAN: PhotoDownloadPlanPresentation = Object.freeze({
  id: 'plan-57',
  itemCount: 57,
  qualities: ['original', 'optimized'] as const,
  estimatedBytes: { original: 4 * 1024 ** 3, optimized: 720 * 1024 ** 2 },
  canStart: { original: false, optimized: true },
  availableDeviceBytes: 2 * 1024 ** 3,
  substantial: { original: true, optimized: true },
});

test('requires an explicit quality and Wi-Fi policy before activating a bounded plan', async () => {
  const confirm = jest.fn();
  const screen = await render(
    <PhotoDownloadPlanModal
      busy={false}
      onCancel={jest.fn()}
      onConfirm={confirm}
      plan={PLAN}
    />,
  );

  expect(screen.getByText('Estimated download size: 720 MB')).toBeTruthy();
  expect(screen.getByText('2.0 GB available on this device')).toBeTruthy();
  expect(screen.getByRole('radio', { name: 'Optimized for this device' }).props.accessibilityState)
    .toEqual({ checked: true });

  await fireEvent(screen.getByRole('switch'), 'valueChange', false);
  await fireEvent.press(screen.getByRole('button', { name: 'Start private download' }));

  expect(confirm).toHaveBeenCalledWith('optimized', false);
}, 15_000);

test('prevents queue activation when the selected quality exceeds the plan storage boundary', async () => {
  const confirm = jest.fn();
  const screen = await render(
    <PhotoDownloadPlanModal
      busy={false}
      onCancel={jest.fn()}
      onConfirm={confirm}
      plan={PLAN}
    />,
  );

  await fireEvent.press(screen.getByRole('radio', { name: 'Original quality' }));
  const start = screen.getByRole('button', { name: 'Start private download' });

  expect(screen.getByText('There is not enough private device storage for this download.')).toBeTruthy();
  expect(start.props.accessibilityState).toMatchObject({ disabled: true });
  await fireEvent.press(start);
  expect(confirm).not.toHaveBeenCalled();
});
