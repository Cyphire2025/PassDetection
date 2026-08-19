/* eslint-disable @typescript-eslint/no-require-imports -- Jest factories load mocked host components after hoisting. */
import { act, render, waitFor } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';

import {
  loadManagerDocumentPreview,
  removeManagerDocumentPreview,
  type ManagerPreview,
} from '@/features/manager/data/manager-document-preview';

import ManagerDocumentPreviewScreen from '../preview';

const mockParams = {
  tripId: '55555555-5555-4555-8555-555555555555',
  passengerId: '22222222-2222-4222-8222-222222222222',
  documentType: 'visa',
  title: 'Visa',
};

jest.mock('expo-router', () => ({ useLocalSearchParams: () => mockParams }));
jest.mock('expo-image', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    Image: (props: Record<string, unknown>) => React.createElement(EventView, {
      ...props,
      testID: 'manager-image-preview',
    }),
  };
});
jest.mock('react-native-pdf', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  const EventView = MockView as React.ComponentType<Record<string, unknown>>;
  return {
    __esModule: true,
    default: (props: Record<string, unknown>) => React.createElement(EventView, {
      ...props,
      testID: 'manager-pdf-preview',
    }),
  };
});
jest.mock('@/features/manager/data/manager-document-preview', () => ({
  loadManagerDocumentPreview: jest.fn(),
  removeManagerDocumentPreview: jest.fn(),
}));
jest.mock('@/core/security/sensitive-screen-protection', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    SensitiveScreenProtection: ({ protectionKey }: { protectionKey: string }) => (
      React.createElement(MockView, {
        accessibilityLabel: protectionKey,
        testID: 'sensitive-screen-protection',
      })
    ),
  };
});
jest.mock('@/design/components/content-state', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return {
    ContentError: ({ message }: { message: string }) => React.createElement(MockText, null, message),
    ContentLoading: ({ label }: { label: string }) => React.createElement(MockText, null, label),
  };
});
jest.mock('@/design/components/screen', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    Screen: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
  };
});
jest.mock('@/features/coordinator/ui/operation-header', () => {
  const React = require('react') as typeof import('react');
  const { Text: MockText } = require('react-native') as typeof import('react-native');
  return {
    OperationHeader: ({ title }: { title: string }) => React.createElement(MockText, null, title),
  };
});

const mockedLoadPreview = jest.mocked(loadManagerDocumentPreview);
const mockedRemovePreview = jest.mocked(removeManagerDocumentPreview);

function preview(uri: string, contentType: string): ManagerPreview {
  return {
    contentType,
    file: { exists: true, name: uri.split('/').at(-1) ?? 'preview', uri },
  } as ManagerPreview;
}

beforeEach(() => {
  jest.clearAllMocks();
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('never stores a manager image preview in the renderer cache', async () => {
  mockedLoadPreview.mockResolvedValueOnce(preview('file:///cache/visa.jpg', 'image/jpeg'));

  const screen = await render(<ManagerDocumentPreviewScreen />);

  await waitFor(() => expect(screen.getByTestId('manager-image-preview')).toBeTruthy());
  expect(screen.getByTestId('manager-image-preview').props.cachePolicy).toBe('none');
  expect(screen.getByTestId('sensitive-screen-protection').props.accessibilityLabel)
    .toBe('manager-document-preview');
});

test('disables PDF renderer caching and removes plaintext across the background boundary', async () => {
  let emitAppState: ((state: AppStateStatus) => void) | undefined;
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    emitAppState = listener;
    return { remove: jest.fn() };
  });
  const first = preview('file:///cache/visa-first.pdf', 'application/pdf');
  const second = preview('file:///cache/visa-second.pdf', 'application/pdf');
  mockedLoadPreview.mockResolvedValueOnce(first).mockResolvedValueOnce(second);

  const screen = await render(<ManagerDocumentPreviewScreen />);
  await waitFor(() => expect(screen.getByTestId('manager-pdf-preview')).toBeTruthy());
  expect(screen.getByTestId('manager-pdf-preview').props.source).toEqual({
    uri: first.file.uri,
    cache: false,
  });

  await act(async () => {
    emitAppState?.('background');
    await Promise.resolve();
  });
  expect(mockedRemovePreview).toHaveBeenCalledWith(first);
  expect(screen.queryByTestId('manager-pdf-preview')).toBeNull();

  await act(async () => {
    emitAppState?.('active');
    await Promise.resolve();
  });
  await waitFor(() => expect(mockedLoadPreview).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId('manager-pdf-preview').props.source).toEqual({
    uri: second.file.uri,
    cache: false,
  });
});
