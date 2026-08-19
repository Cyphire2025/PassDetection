import {
  englishMessages,
  type MessageCatalog,
  type MessageKey,
} from '../messages';
import { createPseudoMessageCatalog, pseudolocalize } from '../pseudolocale';

type MessageSamples = {
  readonly [Key in MessageKey]: Parameters<MessageCatalog[Key]>;
};

const messageSamples = {
  appInterruptedTitle: [],
  appInterruptedMessage: [],
  appRecoveryFailed: [],
  availableOffline: [],
  countdownAccessibility: [2],
  countdownPending: [],
  dateUnavailable: [],
  datesBeingPrepared: [],
  daysLeft: [2],
  demoModeBanner: [],
  departure: [],
  downloadingRequiredDocuments: [],
  hidePassword: [],
  loading: [],
  offlineSavedTripData: [],
  preparingOfflineAccess: [],
  recoveringApp: [],
  restartApp: [],
  returnsOn: ['Aug 21, 2026'],
  secureDownloadPrivacyNote: [],
  showPassword: [],
  signOutSafely: [],
  today: [],
  tripCompleted: [],
  tripCompletedAfter: [9],
  tripDay: [3],
  tripDayUnderway: ['third'],
  tryAgain: [],
  updatedOn: ['Aug 19, 2026'],
} as const satisfies MessageSamples;

function renderMessage<Key extends MessageKey>(
  catalog: MessageCatalog,
  key: Key,
  parameters: Parameters<MessageCatalog[Key]>,
): string {
  const factory = catalog[key] as unknown as (...args: unknown[]) => string;
  return factory(...parameters);
}

describe('reviewed message catalog', () => {
  it('has non-empty reviewed English copy and a typed sample for every key', () => {
    expect(Object.keys(messageSamples).sort()).toEqual(Object.keys(englishMessages).sort());
    for (const key of Object.keys(englishMessages) as MessageKey[]) {
      expect(renderMessage(englishMessages, key, messageSamples[key]).trim()).not.toBe('');
    }
    expect(Object.isFrozen(englishMessages)).toBe(true);
  });

  it('preserves exact current pluralized English wording', () => {
    expect(englishMessages.daysLeft(1)).toBe('1 day left');
    expect(englishMessages.daysLeft(2)).toBe('2 days left');
    expect(englishMessages.tripCompletedAfter(1)).toBe('Trip completed after 1 day');
  });

  it.each(['en-XA', 'ar-XB'] as const)(
    'generates a complete %s pseudolocale from reviewed copy',
    (locale) => {
      const pseudo = createPseudoMessageCatalog(locale);
      expect(Object.keys(pseudo).sort()).toEqual(Object.keys(englishMessages).sort());
      expect(pseudo.daysLeft(2)).toContain('2');
      expect(pseudo.daysLeft(2).length).toBeGreaterThan(englishMessages.daysLeft(2).length);
      expect(Object.isFrozen(pseudo)).toBe(true);
    },
  );

  it('exercises both expanded LTR and mirrored RTL stress copy', () => {
    expect(pseudolocalize('Open visa', 'en-XA')).toBe('⟦ ÖÖþëëñ ṽîîšåå ⟧');
    expect(pseudolocalize('Open visa', 'ar-XB')).toBe('⟦ ååšîîṽ ñëëþÖÖ ⟧');
  });
});
