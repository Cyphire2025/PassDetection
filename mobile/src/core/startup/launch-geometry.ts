export type LaunchRect = { x: number; y: number; width: number; height: number };

// Exact visible bounds of the last included 4K frame, not its white margins.
const ink = { x: 553 / 3840, y: 605 / 2160, width: 2734 / 3840, height: 950 / 2160 };

export function fitLaunchLogo(width: number, height: number) {
  const frameWidth = Math.min(width / ink.width, height / ink.height * 16 / 9);
  const frameHeight = frameWidth * 9 / 16;
  return {
    width: frameWidth,
    height: frameHeight,
    left: (width - frameWidth * ink.width) / 2 - frameWidth * ink.x,
    top: (height - frameHeight * ink.height) / 2 - frameHeight * ink.y,
  };
}

export function launchDockGeometry(root: LaunchRect, target: LaunchRect | null) {
  if (!target || !Object.values(root).every(Number.isFinite) || !Object.values(target).every(Number.isFinite)) return null;
  if (root.width <= 0 || root.height <= 0 || target.width <= 0 || target.height <= 0) return null;
  if (target.x < root.x - 1 || target.y < root.y - 1 ||
      target.x + target.width > root.x + root.width + 1 ||
      target.y + target.height > root.y + root.height + 1) return null;
  const width = Math.min(root.width, 720);
  const fitted = fitLaunchLogo(target.width, target.height);
  return {
    translateX: target.x - root.x + fitted.left + fitted.width / 2 - root.width / 2,
    translateY: target.y - root.y + fitted.top + fitted.height / 2 - root.height / 2,
    scale: fitted.width / width,
  };
}
