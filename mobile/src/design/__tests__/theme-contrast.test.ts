import { colors } from '@/design/theme';

function relativeLuminance(hex: string): number {
  const channel = (offset: number) => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };

  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe('mobile theme contrast', () => {
  it('uses the requested lime as the primary accent', () => {
    expect(colors.green).toBe('#CACF42');
  });

  it('keeps text readable on lime and lime-tinted surfaces', () => {
    expect(contrastRatio(colors.ink, colors.green)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(colors.greenDeep, colors.white)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(colors.greenDeep, colors.greenSoft)).toBeGreaterThanOrEqual(4.5);
  });
});
