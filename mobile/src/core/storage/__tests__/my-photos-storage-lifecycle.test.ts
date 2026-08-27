import {
  beginMyPhotosTemporaryWrite,
  deleteMyPhotosTripRoot,
  purgeMyPhotosTemporaryRoots,
} from '../my-photos-storage-lifecycle';

jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA256' },
  digestStringAsync: jest.fn(async () => 'a'.repeat(64)),
}));

jest.mock('expo-file-system', () => ({
  Paths: { cache: '/cache', document: '/document' },
  Directory: class MockDirectory {
    exists = false;
    uri = 'file:///managed';
    create() {}
    delete() {}
  },
}));

jest.mock('../ios-backup', () => ({ excludeAppPrivateUriFromBackup: jest.fn() }));

describe('My Photos managed root lifecycle', () => {
  it.each(['..', '../trip', 'trip/child', 'trip\\child', '%2e%2e']) (
    'rejects unsafe trip cleanup segment %s',
    async (tripId) => {
      await expect(deleteMyPhotosTripRoot('agency.account', tripId)).rejects.toThrow('Invalid');
    },
  );

  it.each(['decrypted view', 'legacy plaintext cleanup']) (
    'waits for an active %s before purging temporary roots',
    async () => {
      const releaseWrite = beginMyPhotosTemporaryWrite();
      let purgeFinished = false;
      const purge = purgeMyPhotosTemporaryRoots().then(() => {
        purgeFinished = true;
      });

      await Promise.resolve();
      expect(purgeFinished).toBe(false);
      expect(() => beginMyPhotosTemporaryWrite()).toThrow('cleanup is still in progress');

      releaseWrite();
      await purge;
      expect(purgeFinished).toBe(true);
      const releaseNextWrite = beginMyPhotosTemporaryWrite();
      releaseNextWrite();
    },
  );
});
