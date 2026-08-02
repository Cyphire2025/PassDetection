module.exports = {
  preset: 'jest-expo',
  roots: ['<rootDir>/src'],
  modulePathIgnorePatterns: ['<rootDir>/.quarantine/'],
  watchPathIgnorePatterns: ['<rootDir>/.quarantine/'],
  testMatch: ['**/__tests__/**/*.test.[jt]s?(x)'],
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/app/**/_layout.tsx',
  ],
};
