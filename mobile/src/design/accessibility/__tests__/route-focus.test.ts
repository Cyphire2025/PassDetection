import {
  moveAccessibilityFocus,
  type AccessibilityFocusServices,
} from '../use-accessibility-route-focus';

function services(enabled: boolean, reactTag: number | null = 42) {
  const setFocus = jest.fn();
  const findNode = jest.fn(() => reactTag);
  const value: AccessibilityFocusServices = {
    isScreenReaderEnabled: jest.fn(async () => enabled),
    findNode,
    setFocus,
  };
  return { value, setFocus, findNode };
}

describe('route accessibility focus', () => {
  it('moves focus to the route heading only when a screen reader is active', async () => {
    const active = services(true);
    await expect(moveAccessibilityFocus({}, active.value)).resolves.toBe(true);
    expect(active.findNode).toHaveBeenCalledTimes(1);
    expect(active.setFocus).toHaveBeenCalledWith(42);

    const inactive = services(false);
    await expect(moveAccessibilityFocus({}, inactive.value)).resolves.toBe(false);
    expect(inactive.findNode).not.toHaveBeenCalled();
    expect(inactive.setFocus).not.toHaveBeenCalled();
  });

  it('does not focus a route that was cancelled during navigation', async () => {
    const active = services(true);
    await expect(moveAccessibilityFocus({}, active.value, () => true)).resolves.toBe(false);
    expect(active.setFocus).not.toHaveBeenCalled();
  });

  it('fails open when the native accessibility service rejects', async () => {
    const setFocus = jest.fn();
    await expect(moveAccessibilityFocus({}, {
      isScreenReaderEnabled: jest.fn(async () => { throw new Error('native unavailable'); }),
      findNode: jest.fn(() => 42),
      setFocus,
    })).resolves.toBe(false);
    expect(setFocus).not.toHaveBeenCalled();
  });
});
