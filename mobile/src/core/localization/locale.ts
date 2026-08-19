import type { Locale } from 'expo-localization';

import type { PseudoLocale } from './pseudolocale';

export const DEFAULT_MESSAGE_LOCALE = 'en-IN';
export const REVIEWED_MESSAGE_LANGUAGES = Object.freeze(['en'] as const);

export type LayoutDirection = 'ltr' | 'rtl';

export type LocalizationResolution = Readonly<{
  messageLanguage: 'en';
  formattingLocale: string;
  direction: LayoutDirection;
  pseudoLocale: PseudoLocale | null;
}>;

type LocalePreference = Pick<Locale, 'languageCode' | 'languageTag'>;

function isSafeEnglishLocale(value: string): boolean {
  const normalized = value.trim();
  if (!/^en(?:-[A-Za-z0-9]{2,8})*$/.test(normalized)) return false;
  try {
    // DateTimeFormat is available in supported Hermes builds. Construction is
    // also a safer compatibility check than Intl.Locale on older runtimes.
    return new Intl.DateTimeFormat(normalized).resolvedOptions().locale.length > 0;
  } catch {
    return false;
  }
}

export function resolveLocalization(
  preferences: readonly LocalePreference[],
  pseudoLocale: PseudoLocale | null = null,
): LocalizationResolution {
  if (pseudoLocale) {
    return {
      messageLanguage: 'en',
      formattingLocale: pseudoLocale === 'en-XA' ? 'en-US' : DEFAULT_MESSAGE_LOCALE,
      direction: pseudoLocale === 'ar-XB' ? 'rtl' : 'ltr',
      pseudoLocale,
    };
  }

  const supportedPreference = preferences.find((preference) => (
    preference.languageCode?.toLowerCase() === 'en'
      && isSafeEnglishLocale(preference.languageTag)
  ));

  return {
    messageLanguage: 'en',
    formattingLocale: supportedPreference?.languageTag ?? DEFAULT_MESSAGE_LOCALE,
    // English is the only reviewed message catalog. Do not switch the visual
    // direction merely because an unsupported device language is RTL.
    direction: 'ltr',
    pseudoLocale: null,
  };
}

export function formatInteger(
  value: number,
  locale: string = DEFAULT_MESSAGE_LOCALE,
): string {
  if (!Number.isFinite(value)) return '—';
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
  } catch {
    return String(Math.round(value));
  }
}
