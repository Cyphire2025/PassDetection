/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { render } from '@testing-library/react-native';

import { ContentEmpty } from '../content-state';
import { PrimaryButton } from '../primary-button';
import { StatusPill } from '../status-pill';

jest.mock('lucide-react-native/icons/refresh-cw', () => {
  const React = require('react') as typeof import('react');
  const { View } = require('react-native') as typeof import('react-native');
  return { __esModule: true, default: () => React.createElement(View) };
});

describe('shared accessibility primitives', () => {
  it('keeps a loading action named and exposes busy/disabled state', async () => {
    const screen = await render(<PrimaryButton label="Continue" loading />);
    const button = screen.getByLabelText('Continue');

    expect(button.props.accessibilityRole).toBe('button');
    expect(button.props.accessibilityState).toEqual({ disabled: true, busy: true });
  });

  it('gives status and empty-state copy explicit semantics', async () => {
    const screen = await render(
      <>
        <StatusPill label="Available offline" tone="good" />
        <ContentEmpty title="No documents" message="Documents will appear here." />
      </>,
    );

    expect(screen.getByLabelText('Available offline').props.accessibilityRole).toBe('text');
    expect(screen.getByRole('header')).toHaveTextContent('No documents');
  });
});
