import {
  MAXIMUM_NAVIGATION_WIDTH,
  MAXIMUM_READABLE_CONTENT_WIDTH,
  responsiveContentLayout,
  responsiveNavigationLayout,
} from '../layout-policy';

describe('responsive and large-text layout policy', () => {
  it('preserves phone spacing and constrains tablet reading width', () => {
    expect(responsiveContentLayout(320)).toEqual({
      horizontalPadding: 12,
      maximumWidth: 320,
    });
    expect(responsiveContentLayout(430)).toEqual({
      horizontalPadding: 16,
      maximumWidth: 430,
    });
    expect(responsiveContentLayout(1_366)).toEqual({
      horizontalPadding: 32,
      maximumWidth: MAXIMUM_READABLE_CONTENT_WIDTH,
    });
  });

  it('bounds malformed dimensions instead of producing invalid styles', () => {
    expect(responsiveContentLayout(Number.NaN)).toEqual({
      horizontalPadding: 16,
      maximumWidth: 360,
    });
  });

  it('centers a bounded tablet tab bar and grows it for large text', () => {
    const normal = responsiveNavigationLayout(1_366, 1);
    const large = responsiveNavigationLayout(1_366, 2);
    expect(normal.barWidth).toBe(MAXIMUM_NAVIGATION_WIDTH);
    expect(large.barWidth).toBe(MAXIMUM_NAVIGATION_WIDTH);
    expect(large.barMinimumHeight).toBeGreaterThan(normal.barMinimumHeight);
    expect(large.itemMinimumHeight).toBeGreaterThan(normal.itemMinimumHeight);
    expect(large.labelMaximumFontScale).toBe(2);
  });
});
