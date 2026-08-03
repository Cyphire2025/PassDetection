export type DocumentPreloadOutcome = {
  completed: number;
  failed: number;
  total: number;
};

export type DocumentPreloadStatus = {
  message: string;
  completedLabel: string;
};

export function documentPreloadStatus(
  subject: string,
  outcome: DocumentPreloadOutcome,
): DocumentPreloadStatus {
  if (outcome.failed > 0) {
    return {
      message: `${subject} is available`,
      completedLabel: `${outcome.completed} of ${outcome.total} documents are ready offline; ${outcome.failed} will retry later`,
    };
  }
  return {
    message: `${subject} is ready`,
    completedLabel: outcome.total > 0
      ? `All ${outcome.total} documents are ready offline`
      : 'Offline trip information is ready',
  };
}
