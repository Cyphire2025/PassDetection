import { documentPreloadStatus } from '../preload-status';

test('reports complete document preparation without overstating an empty manifest', () => {
  expect(documentPreloadStatus('Your trip', { completed: 3, failed: 0, total: 3 })).toEqual({
    message: 'Your trip is ready',
    completedLabel: 'All 3 documents are ready offline',
  });
  expect(documentPreloadStatus('Your trip', { completed: 0, failed: 0, total: 0 }).completedLabel)
    .toBe('Offline trip information is ready');
});

test('keeps document failures non-blocking while clearly promising a later retry', () => {
  expect(documentPreloadStatus('Your trip', { completed: 2, failed: 1, total: 3 })).toEqual({
    message: 'Your trip is available',
    completedLabel: '2 of 3 documents are ready offline; 1 will retry later',
  });
});
