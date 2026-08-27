import {
  MOBILE_LIST_WINDOWING,
  MOBILE_REQUEST_BUDGET,
  MOBILE_STATIC_ASSET_BUDGET,
  MY_PHOTOS_CLIENT_BUDGET,
} from '../mobile-performance-budgets';
import {
  MY_PHOTOS_MAX_RESIDENT_ITEMS,
  MY_PHOTOS_MAX_RESIDENT_PAGES,
  MY_PHOTOS_PAGE_SIZE,
} from '@/features/my-photos/data/gallery-window';
import {
  ACTIVE_ATTENDANCE_MIN_REFRESH_MS,
} from '@/core/query/attendance-refresh-policy';
import { mobileQueryClient, shouldRetryQuery } from '@/core/query/query-client';
import { SELECTED_TRIP_FALLBACK_INTERVAL_MS } from '@/core/sync/sync-runtime-policy';

type DirectoryEntry = Readonly<{
  name: string;
  isDirectory: () => boolean;
}>;

type BinaryFile = Readonly<{
  length: number;
  readUInt32BE: (offset: number) => number;
  toString: (encoding: string, start: number, end: number) => string;
}>;

type FileSystem = Readonly<{
  readFileSync: {
    (filePath: string, encoding: 'utf8'): string;
    (filePath: string): BinaryFile;
  };
  readdirSync: {
    (directory: string): string[];
    (directory: string, options: { withFileTypes: true }): DirectoryEntry[];
  };
  statSync: (filePath: string) => { size: number };
}>;

type PathModule = Readonly<{
  basename: (filePath: string) => string;
  join: (...parts: string[]) => string;
  relative: (from: string, to: string) => string;
}>;

const fileSystem = jest.requireActual<FileSystem>('fs');
const pathModule = jest.requireActual<PathModule>('path');
const processModule = jest.requireActual<{ cwd: () => string }>('process');
const MOBILE_ROOT = processModule.cwd();
const SOURCE_ROOT = pathModule.join(MOBILE_ROOT, 'src');

function filesBelow(directory: string, extension: string): string[] {
  const files: string[] = [];
  for (const entry of fileSystem.readdirSync(directory, { withFileTypes: true })) {
    const absolutePath = pathModule.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== '__tests__') files.push(...filesBelow(absolutePath, extension));
    } else if (entry.name.endsWith(extension)) {
      files.push(absolutePath);
    }
  }
  return files;
}

function source(relativePath: string): string {
  return fileSystem.readFileSync(pathModule.join(MOBILE_ROOT, relativePath), 'utf8');
}

function pngDimensions(filePath: string): { width: number; height: number } {
  const bytes = fileSystem.readFileSync(filePath);
  if (bytes.length < 24 || bytes.toString('ascii', 1, 4) !== 'PNG') {
    throw new Error(`${pathModule.basename(filePath)} is not a readable PNG asset.`);
  }
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

describe('mobile virtualized-list budgets', () => {
  it('keeps every shared profile inside conservative render-work bounds', () => {
    for (const budget of Object.values(MOBILE_LIST_WINDOWING)) {
      expect(Number.isSafeInteger(budget.initialNumToRender)).toBe(true);
      expect(budget.initialNumToRender).toBeGreaterThanOrEqual(1);
      expect(budget.initialNumToRender).toBeLessThanOrEqual(budget.maxToRenderPerBatch);
      expect(budget.maxToRenderPerBatch).toBeLessThanOrEqual(24);
      expect(budget.updateCellsBatchingPeriod).toBeGreaterThanOrEqual(32);
      expect(budget.windowSize).toBeGreaterThanOrEqual(5);
      expect(budget.windowSize).toBeLessThanOrEqual(7);
      expect(budget.windowSize % 2).toBe(1);
      expect(Object.isFrozen(budget)).toBe(true);
    }
  });

  it('keeps My Photos declared budgets aligned with its bounded cursor window', () => {
    expect(MY_PHOTOS_CLIENT_BUDGET.pageSize).toBe(MY_PHOTOS_PAGE_SIZE);
    expect(MY_PHOTOS_CLIENT_BUDGET.maximumResidentPages).toBe(MY_PHOTOS_MAX_RESIDENT_PAGES);
    expect(MY_PHOTOS_CLIENT_BUDGET.maximumResidentMetadataItems).toBe(MY_PHOTOS_MAX_RESIDENT_ITEMS);
    expect(MY_PHOTOS_CLIENT_BUDGET.maximumResidentMetadataItems).toBeLessThanOrEqual(240);
  });

  it('requires every production FlatList and SectionList to use a shared profile', () => {
    const offenders: string[] = [];
    for (const filePath of filesBelow(SOURCE_ROOT, '.tsx')) {
      const contents = fileSystem.readFileSync(filePath, 'utf8');
      const listCount = (contents.match(/<(?:FlatList|SectionList)(?=[<\s])/g) ?? []).length;
      if (listCount === 0) continue;
      const budgetCount = (contents.match(/\{\.\.\.MOBILE_LIST_WINDOWING\.[A-Za-z]+\}/g) ?? []).length;
      if (budgetCount !== listCount || contents.includes('removeClippedSubviews')) {
        offenders.push(pathModule.relative(SOURCE_ROOT, filePath));
      }
    }
    expect(offenders).toEqual([]);
  });

  it('keeps high-cardinality search input decoupled from list recomputation', () => {
    const searchContracts = [
      ['src/app/(passenger)/select-trip.tsx', 'useDeferredValue'],
      ['src/app/(manager)/(tabs)/groups.tsx', 'useDeferredValue'],
      ['src/app/(coordinator)/(tabs)/groups.tsx', 'useDeferredValue'],
      ['src/app/(manager)/operations/passengers.tsx', 'useDebouncedValue'],
      ['src/app/(coordinator)/(tabs)/passengers.tsx', 'useDebouncedValue'],
    ] as const;
    for (const [filePath, primitive] of searchContracts) {
      const contents = source(filePath);
      expect(contents).toContain(primitive);
      expect(contents).toContain('useMemo');
    }
  });
});

describe('mobile request and render-work budgets', () => {
  it('prevents overlapping framework refetches and unbounded automatic retries', () => {
    const queries = mobileQueryClient.getDefaultOptions().queries;
    expect(queries?.refetchOnReconnect).toBe(false);
    expect(queries?.refetchOnWindowFocus).toBe(false);
    expect(shouldRetryQuery(
      MOBILE_REQUEST_BUDGET.maximumAutomaticQueryRetries,
      new TypeError('offline'),
    )).toBe(false);
    expect(ACTIVE_ATTENDANCE_MIN_REFRESH_MS)
      .toBeGreaterThanOrEqual(MOBILE_REQUEST_BUDGET.minimumForegroundPollingMs);
    expect(SELECTED_TRIP_FALLBACK_INTERVAL_MS)
      .toBeGreaterThanOrEqual(MOBILE_REQUEST_BUDGET.minimumLifecycleFallbackMs);
  });

  it('retains two-worker ceilings for full sync and background preparation', () => {
    expect(source('src/core/sync/sync-service.ts'))
      .toMatch(/FULL_SYNC_CONCURRENCY\s*=\s*2/);
    expect(source('src/core/sync/sync-trigger.ts'))
      .toMatch(/MAX_COORDINATED_TRIP_CONCURRENCY\s*=\s*2/);
    expect(source('src/core/sync/workspace-background-preload.ts'))
      .toMatch(/WORKSPACE_BACKGROUND_PRELOAD_CONCURRENCY\s*=\s*2/);
  });

  it('keeps compiler memoization and reduced-effects capability fallbacks enabled', () => {
    const appConfig = source('app.config.ts');
    expect(appConfig).toMatch(/jsEngine:\s*["']hermes["']/);
    expect(appConfig).toMatch(/reactCompiler:\s*true/);
    for (const filePath of [
      'src/design/components/ambient-hero-glow.tsx',
      'src/design/components/hero-particles.tsx',
      'src/design/components/primary-button.tsx',
      'src/features/auth/ui/countdown-progress.tsx',
    ]) {
      expect(source(filePath)).toContain('useReducedMotion');
    }
    const tabBar = source('src/design/navigation/floating-tab-bar.tsx');
    expect(tabBar).toContain('reduceTransparency');
    expect(tabBar).toContain('Device.deviceYearClass');
    expect(tabBar).toContain('styles.fallback');
  });
});

describe('bundled static-asset budgets', () => {
  it('bounds compressed bytes, decode dimensions, and asset count', () => {
    const imageDirectory = pathModule.join(MOBILE_ROOT, 'assets/images');
    const images = fileSystem.readdirSync(imageDirectory)
      .filter((name) => name.toLowerCase().endsWith('.png'))
      .map((name) => pathModule.join(imageDirectory, name));
    const totalBytes = images.reduce(
      (total, filePath) => total + fileSystem.statSync(filePath).size,
      0,
    );

    expect(images.length).toBeLessThanOrEqual(MOBILE_STATIC_ASSET_BUDGET.bundledImageCount);
    expect(totalBytes).toBeLessThanOrEqual(MOBILE_STATIC_ASSET_BUDGET.bundledImageBytes);
    for (const filePath of images) {
      const dimensions = pngDimensions(filePath);
      expect(fileSystem.statSync(filePath).size).toBeLessThanOrEqual(
        MOBILE_STATIC_ASSET_BUDGET.singleImageBytes,
      );
      expect(dimensions.width * dimensions.height).toBeLessThanOrEqual(
        MOBILE_STATIC_ASSET_BUDGET.singleImagePixels,
      );
    }
  });
});
