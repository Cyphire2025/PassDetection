// English is the only human-reviewed copy catalog. Every future translation
// must satisfy MessageCatalog, so a missing or incorrectly parameterized key
// fails TypeScript before it can reach a release build.
export const englishMessages = Object.freeze({
  appInterruptedTitle: () => 'Something interrupted the app.',
  appInterruptedMessage: () => (
    'Your private trip data remains protected. Try restoring this screen or restart the app.'
  ),
  appRecoveryFailed: () => (
    'The app could not finish that recovery step. Restart and try again.'
  ),
  availableOffline: () => 'Available offline',
  countdownAccessibility: (calendarDays: number) => (
    `${calendarDays} ${calendarDays === 1 ? 'day' : 'days'} until departure`
  ),
  countdownPending: () => 'Countdown appears when dates are confirmed',
  dateUnavailable: () => 'Date unavailable',
  datesBeingPrepared: () => 'Dates being prepared',
  daysLeft: (count: number) => `${count} ${count === 1 ? 'day' : 'days'} left`,
  demoModeBanner: () => 'LOCAL EMULATOR DEMO · NO SERVER CONNECTION',
  departure: () => 'Departure',
  downloadingRequiredDocuments: () => 'Downloading required documents',
  hidePassword: () => 'Hide password',
  loading: () => 'Loading',
  offlineSavedTripData: () => 'Offline — using saved trip data',
  preparingOfflineAccess: () => 'Preparing offline access',
  recoveringApp: () => 'Recovering app',
  restartApp: () => 'Restart app',
  returnsOn: (date: string) => `Returns ${date}`,
  showPassword: () => 'Show password',
  signOutSafely: () => 'Sign out safely',
  today: () => 'Today',
  tripCompleted: () => 'Trip completed',
  tripCompletedAfter: (dayCount: number) => (
    `Trip completed after ${dayCount} ${dayCount === 1 ? 'day' : 'days'}`
  ),
  tripDay: (dayNumber: number) => `Trip day ${dayNumber}`,
  tripDayUnderway: (ordinalDay: string) => `Your ${ordinalDay} trip day is underway`,
  tryAgain: () => 'Try again',
  updatedOn: (date: string) => `Updated ${date}`,
  secureDownloadPrivacyNote: () => (
    'Keep the app open. Encrypted copies stay private to this account and device.'
  ),
} as const);

export type MessageCatalog = Readonly<typeof englishMessages>;
export type MessageKey = keyof MessageCatalog;

export type CompatibleMessageCatalog = {
  readonly [Key in MessageKey]: (
    ...args: Parameters<MessageCatalog[Key]>
  ) => string;
};

export function defineCompleteMessageCatalog(
  catalog: CompatibleMessageCatalog,
): Readonly<CompatibleMessageCatalog> {
  return Object.freeze(catalog);
}
