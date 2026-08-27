import { render } from '@testing-library/react-native';

import { MyPhotosManagementCard } from '../my-photos-management-card';

jest.mock('lucide-react-native/icons/eraser', () => () => null);
jest.mock('lucide-react-native/icons/scan-face', () => () => null);
jest.mock('lucide-react-native/icons/shield-x', () => () => null);
jest.mock('lucide-react-native/icons/trash-2', () => () => null);

test('keeps local encrypted-copy cleanup available while disabling unavailable server deletion', async () => {
  const screen = await render(
    <MyPhotosManagementCard
      busy={false}
      onClearStorage={jest.fn()}
      onDeleteEnrollment={jest.fn()}
      onRemoveDownloads={jest.fn()}
      serverActionsAvailable={false}
    />,
  );

  expect(screen.getByRole('button', { name: /Remove downloaded copies/i }).props.accessibilityState)
    .toMatchObject({ disabled: false });
  expect(screen.getByRole('button', { name: /Clear My Photos storage/i }).props.accessibilityState)
    .toMatchObject({ disabled: false });
  expect(screen.getByRole('button', { name: /Delete Face Scan/i }).props.accessibilityState)
    .toMatchObject({ disabled: true });
  expect(screen.getByRole('button', { name: /Remove my face-search data/i }).props.accessibilityState)
    .toMatchObject({ disabled: true });
  expect(screen.getByRole('alert')).toHaveTextContent(/My Photos could not be refreshed/);
});
