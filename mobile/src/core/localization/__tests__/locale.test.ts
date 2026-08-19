import { formatInteger, resolveLocalization } from '../locale';

const locale = (
  languageTag: string,
  languageCode: string | null,
) => ({ languageTag, languageCode });

describe('application locale resolution', () => {
  it('selects the first reviewed English preference and keeps its regional formatting', () => {
    expect(resolveLocalization([
      locale('fr-FR', 'fr'),
      locale('en-GB', 'en'),
      locale('en-US', 'en'),
    ])).toEqual({
      messageLanguage: 'en',
      formattingLocale: 'en-GB',
      direction: 'ltr',
      pseudoLocale: null,
    });
  });

  it('falls back to reviewed English instead of pretending an RTL translation exists', () => {
    expect(resolveLocalization([
      locale('ar-SA', 'ar'),
      locale('invalid locale', null),
    ])).toEqual({
      messageLanguage: 'en',
      formattingLocale: 'en-IN',
      direction: 'ltr',
      pseudoLocale: null,
    });
  });

  it('allows explicit test-only pseudo directions', () => {
    expect(resolveLocalization([], 'en-XA').direction).toBe('ltr');
    expect(resolveLocalization([], 'ar-XB').direction).toBe('rtl');
  });

  it('formats finite integers and fails safely when Intl.NumberFormat is unavailable', () => {
    expect(formatInteger(12_345, 'en-IN')).toBe('12,345');
    expect(formatInteger(Number.NaN)).toBe('—');

    const original = Intl.NumberFormat;
    Object.defineProperty(Intl, 'NumberFormat', {
      configurable: true,
      value: undefined,
      writable: true,
    });
    try {
      expect(formatInteger(12_345, 'en-IN')).toBe('12345');
    } finally {
      Object.defineProperty(Intl, 'NumberFormat', {
        configurable: true,
        value: original,
        writable: true,
      });
    }
  });
});
