/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { fireEvent, render } from '@testing-library/react-native';

import { TextField } from '../text-field';

jest.mock('lucide-react-native/icons/eye', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});
jest.mock('lucide-react-native/icons/eye-off', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(MockView) };
});

test('lets staff reveal and hide a typed password without changing its value', async () => {
  const onChangeText = jest.fn();
  const screen = await render(
    <TextField
      label="Password"
      value="enterprise-secret"
      secureTextEntry
      showPasswordToggle
      onChangeText={onChangeText}
    />,
  );

  expect(screen.getByLabelText('Password').props.secureTextEntry).toBe(true);
  await fireEvent.press(screen.getByLabelText('Show password'));
  expect(screen.getByLabelText('Password').props.secureTextEntry).toBe(false);
  expect(screen.getByLabelText('Password').props.value).toBe('enterprise-secret');
  await fireEvent.press(screen.getByLabelText('Hide password'));
  expect(screen.getByLabelText('Password').props.secureTextEntry).toBe(true);
  expect(onChangeText).not.toHaveBeenCalled();
});
