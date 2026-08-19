declare module 'node:sqlite' {
  export type StatementRunResult = Readonly<{
    changes: bigint | number;
    lastInsertRowid: bigint | number;
  }>;

  export class StatementSync {
    all(...parameters: readonly unknown[]): Record<string, unknown>[];
    get(...parameters: readonly unknown[]): Record<string, unknown> | undefined;
    run(...parameters: readonly unknown[]): StatementRunResult;
  }

  export class DatabaseSync {
    constructor(path: string);
    close(): void;
    exec(sql: string): void;
    prepare(sql: string): StatementSync;
  }
}
