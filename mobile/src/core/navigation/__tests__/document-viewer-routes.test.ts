import {
  coordinatorDocumentViewerRoute,
  managerDocumentViewerRoute,
  passengerDocumentViewerRoute,
} from '../document-viewer-routes';

test('document viewers remain inside the active role navigation stack', () => {
  expect(passengerDocumentViewerRoute).toBe('/(passenger)/document/[id]');
  expect(managerDocumentViewerRoute).toBe('/(manager)/document/[id]');
  expect(coordinatorDocumentViewerRoute).toBe('/(coordinator)/operations/document/[id]');

  for (const route of [
    passengerDocumentViewerRoute,
    managerDocumentViewerRoute,
    coordinatorDocumentViewerRoute,
  ]) {
    expect(route).not.toBe('/document/[id]');
  }
});
