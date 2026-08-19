import {
  defineCompleteMessageCatalog,
  englishMessages,
  type CompatibleMessageCatalog,
} from './messages';

export type PseudoLocale = 'en-XA' | 'ar-XB';

const ACCENTED_CHARACTER: Readonly<Record<string, string>> = Object.freeze({
  A: 'Å', B: 'Ɓ', C: 'Ç', D: 'Ð', E: 'Ë', F: 'Ƒ', G: 'Ĝ', H: 'Ħ', I: 'Î',
  J: 'Ĵ', K: 'Ķ', L: 'Ŀ', M: 'Ḿ', N: 'Ñ', O: 'Ö', P: 'Þ', Q: 'Q', R: 'Ŕ',
  S: 'Š', T: 'Ţ', U: 'Û', V: 'Ṽ', W: 'Ŵ', X: 'Ẍ', Y: 'Ÿ', Z: 'Ž',
  a: 'å', b: 'ƀ', c: 'ç', d: 'ð', e: 'ë', f: 'ƒ', g: 'ĝ', h: 'ħ', i: 'î',
  j: 'ĵ', k: 'ķ', l: 'ŀ', m: 'ḿ', n: 'ñ', o: 'ö', p: 'þ', q: 'q', r: 'ŕ',
  s: 'š', t: 'ţ', u: 'û', v: 'ṽ', w: 'ŵ', x: 'ẍ', y: 'ÿ', z: 'ž',
});

const VOWEL = /[AEIOUaeiou]/;

/**
 * Expands and accents reviewed English copy so clipping, fixed-height, and
 * direction assumptions are visible in automated screenshots. This is a test
 * locale, never a user-facing translation.
 */
export function pseudolocalize(value: string, locale: PseudoLocale): string {
  const transformed = Array.from(value, (character) => {
    const accented = ACCENTED_CHARACTER[character] ?? character;
    return VOWEL.test(character) ? `${accented}${accented}` : accented;
  }).join('');

  return locale === 'ar-XB'
    ? `⟦ ${Array.from(transformed).reverse().join('')} ⟧`
    : `⟦ ${transformed} ⟧`;
}

export function createPseudoMessageCatalog(
  locale: PseudoLocale,
): Readonly<CompatibleMessageCatalog> {
  const catalog = Object.fromEntries(
    Object.entries(englishMessages).map(([key, source]) => [
      key,
      (...args: unknown[]) => pseudolocalize(
        (source as unknown as (...parameters: unknown[]) => string)(...args),
        locale,
      ),
    ]),
  ) as CompatibleMessageCatalog;
  // The runtime adapter is covered by exact key-parity and parameterized-copy
  // tests; the public return type preserves every source factory's tuple.
  return defineCompleteMessageCatalog(catalog);
}
