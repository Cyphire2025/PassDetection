module.exports = {
  preset: 'jest-expo',
  roots: ['<rootDir>/src'],
  modulePathIgnorePatterns: ['<rootDir>/.quarantine/'],
  watchPathIgnorePatterns: ['<rootDir>/.quarantine/'],
  testMatch: ['**/__tests__/**/*.test.[jt]s?(x)'],
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  // The reviewed Ed25519/base64 implementations are ESM-first packages.
  // Transform them alongside Expo's supported native modules in Jest so the
  // same implementation exercised by Hermes is covered by contract tests.
  transformIgnorePatterns: [
    '[\\\\/]node_modules[\\\\/](?!(?:\\.pnpm|react-native|@react-native|@react-native-community|expo|@expo|@expo-google-fonts|react-navigation|@react-navigation|@sentry|native-base|standard-navigation|@noble|@scure))',
    '[\\\\/]node_modules[\\\\/]react-native-reanimated[\\\\/]plugin[\\\\/]',
    '[\\\\/]node_modules[\\\\/]@react-native[\\\\/]babel-preset[\\\\/]',
  ],
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/app/**/_layout.tsx',
  ],
  // This is a regression ratchet over the measured enterprise-hardening
  // baseline, not a claim that aggregate coverage alone proves correctness.
  // Critical security/sync/storage paths also carry focused contract, race,
  // rollback, and failure-mode tests.
  coverageThreshold: {
    global: {
      statements: 57,
      branches: 48,
      functions: 52,
      lines: 60,
    },
  },
};
