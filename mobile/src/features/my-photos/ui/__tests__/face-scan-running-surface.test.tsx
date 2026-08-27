import { render } from '@testing-library/react-native';
import { createElement } from 'react';
import { View } from 'react-native';

import { FaceScanRunningSurface } from '../face-scan-running-surface';

const mockCreateElement = createElement;
const mockView = View;

jest.mock('../face-scan-camera', () => ({
  FaceScanCamera: function MockFaceScanCamera() {
    return mockCreateElement(mockView, { testID: 'javascript-camera-view' });
  },
}));

jest.mock('@/core/security/sensitive-screen-protection', () => ({
  SensitiveScreenProtection: () => null,
}));

const callbacks = {
  onCancel: jest.fn(),
  onCameraUnavailable: jest.fn(),
  onCompleteDevelopmentSimulation: jest.fn(),
} as const;

test('development simulator owns the JavaScript camera guidance surface', async () => {
  const screen = await render(<FaceScanRunningSurface clientFlow="development_simulator" {...callbacks} />);

  expect(screen.getByTestId('javascript-camera-view')).toBeTruthy();
  expect(screen.queryByTestId('face-scan-native-host')).toBeNull();
});

test('native provider host never mounts JavaScript CameraView', async () => {
  const screen = await render(<FaceScanRunningSurface clientFlow="native" {...callbacks} />);

  expect(screen.getByTestId('face-scan-native-host')).toBeTruthy();
  expect(screen.queryByTestId('javascript-camera-view')).toBeNull();
  expect(screen.getByText(/Camera frames and liveness video do not pass through JavaScript/)).toBeTruthy();
});
