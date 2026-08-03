const MANAGED_DATABASE_ARTIFACT = /^(gc_[0-9a-f]{32}\.db)(?:-(?:wal|shm|journal))?$/i;
const MANAGED_DATABASE_MAIN = /^gc_[0-9a-f]{32}\.db$/i;

export function isManagedDatabaseMainName(name: string): boolean {
  return MANAGED_DATABASE_MAIN.test(name);
}

export function managedDatabaseMainNameForArtifact(name: string): string | null {
  return MANAGED_DATABASE_ARTIFACT.exec(name)?.[1] ?? null;
}

export function isManagedDatabaseArtifactName(name: string): boolean {
  return managedDatabaseMainNameForArtifact(name) !== null;
}
