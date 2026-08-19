import { spacing } from '@/design/theme';

export const MINIMUM_TOUCH_TARGET = 48;
export const MAXIMUM_READABLE_CONTENT_WIDTH = 960;
export const MAXIMUM_NAVIGATION_WIDTH = 720;

export type ResponsiveContentLayout = Readonly<{
  horizontalPadding: number;
  maximumWidth: number;
}>;

function finitePositive(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

export function responsiveContentLayout(viewportWidth: number): ResponsiveContentLayout {
  const width = finitePositive(viewportWidth, 360);
  const horizontalPadding = width < 360
    ? spacing.md
    : width < 768
      ? spacing.lg
      : width < 1_200
        ? spacing.xl
        : spacing.xxl;

  return {
    horizontalPadding,
    maximumWidth: Math.min(width, MAXIMUM_READABLE_CONTENT_WIDTH),
  };
}

export type NavigationLayout = Readonly<{
  barWidth: number;
  barMinimumHeight: number;
  itemMinimumHeight: number;
  labelMaximumFontScale: number;
}>;

export function responsiveNavigationLayout(
  viewportWidth: number,
  fontScale: number,
): NavigationLayout {
  const width = finitePositive(viewportWidth, 360);
  const safeFontScale = Math.min(2, Math.max(1, finitePositive(fontScale, 1)));
  const growth = Math.round((safeFontScale - 1) * 20);
  return {
    barWidth: Math.max(0, Math.min(width - spacing.md * 2, MAXIMUM_NAVIGATION_WIDTH)),
    barMinimumHeight: 68 + growth,
    itemMinimumHeight: 58 + growth,
    // Navigation remains fully announced through accessibilityLabel while a
    // bounded visual scale prevents five tabs overlapping at extreme settings.
    labelMaximumFontScale: 2,
  };
}
